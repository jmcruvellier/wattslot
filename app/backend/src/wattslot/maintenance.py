"""Conservation des données et maintenance nocturne (lot 1.4).

Chaque nuit (``MAINTENANCE_AT``, heure locale de la maison), ou à la demande :

1. **Brut** : suppression des journées échues, dossier par dossier (exigence
   mesurée sur un N150, lot 0.5). Une journée n'est supprimée qu'une fois entièrement agrégée.
2. **Agrégats** : suppression des périodes échues, capteur par capteur et graphe par graphe, avec
   un ``flush`` après chaque suppression (règles de mémoire : jamais de transaction de plusieurs
   millions de triplets). Un graphe mensuel vidé est retiré.
3. **Compactage** du magasin principal (``optimize``), qui rend la place des suppressions.

Durées de conservation réglables (``Retention``), gardées en base (``app_settings``) : brut
3 jours, quarts d'heure 35 jours (profils de cycle sur 30 jours), heures sans limite.
"""

import asyncio
import json
import logging
import sqlite3
import time as time_module
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from wattslot.aggregation import HOUR, PERIODS, QUARTER, Aggregator, next_midnight
from wattslot.ontology import BASE, VOCAB
from wattslot.storage.database import DATABASE_FILENAME
from wattslot.storage.graph import GRAPH_DIRNAME, GraphStore
from wattslot.storage.raw import SOSA, XSD, RawStores

logger = logging.getLogger(__name__)

MAINTENANCE_AT = time(3, 30)  # heure locale, en dehors des heures de production
RETENTION_KEY = "retention"


class Retention(BaseModel):
    """Durées de conservation, en jours."""

    raw_days: int = Field(default=3, ge=1, le=30)
    quarter_days: int = Field(
        default=35, ge=31, le=3660
    )  # au moins les 30 jours des profils de cycle
    hour_days: int | None = Field(default=None, ge=366)  # None : sans limite


class DiskUsage(BaseModel):
    raw_bytes: int
    graph_bytes: int
    database_bytes: int


class MaintenanceRun(BaseModel):
    started_at: datetime
    duration_s: float
    removed_days: list[date] = []
    kept_days: list[date] = []  # échues mais pas encore entièrement agrégées
    removed_aggregates: dict[str, int] = {}


class MaintenanceStatus(BaseModel):
    running: bool
    in_progress: bool = False
    next_run_at: datetime | None = None
    last_run: MaintenanceRun | None = None
    last_error: str | None = None
    retention: Retention
    disk: DiskUsage


def load_retention(database: sqlite3.Connection) -> Retention:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (RETENTION_KEY,)
    ).fetchone()
    return Retention.model_validate(json.loads(row[0])) if row else Retention()


def save_retention(database: sqlite3.Connection, retention: Retention) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (RETENTION_KEY, retention.model_dump_json()),
        )


def _size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except FileNotFoundError:
        return 0  # retiré entre-temps par un compactage de RocksDB


def directory_size(path: Path) -> int:
    """Taille d'un fichier ou d'un dossier, mesurée pendant que RocksDB peut le compacter."""
    if not path.is_dir():
        return _size(path)
    total = 0
    try:
        for child in path.rglob("*"):
            total += _size(child)
    except FileNotFoundError:
        pass  # sous-dossier retiré pendant le parcours : mesure partielle, sans erreur
    return total


def _xsd(moment: datetime) -> str:
    return f'"{moment.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"^^<{XSD}dateTime>'


class Maintenance:
    def __init__(
        self,
        raw: RawStores,
        graph: GraphStore,
        database: sqlite3.Connection,
        data_dir: Path,
        aggregator: Aggregator | None = None,
    ) -> None:
        self._raw = raw
        self._graph = graph
        self._database = database
        self._data_dir = data_dir
        self._aggregator = aggregator
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._next_run_at: datetime | None = None
        self._last_run: MaintenanceRun | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def next_run(self, now: datetime) -> datetime:
        local = now.astimezone(self._raw.zone)
        moment = datetime.combine(local.date(), MAINTENANCE_AT, self._raw.zone)
        if moment <= local:
            moment = datetime.combine(
                local.date() + timedelta(days=1), MAINTENANCE_AT, moment.tzinfo
            )
        return moment.astimezone(UTC)

    async def _loop(self) -> None:
        while True:
            self._next_run_at = self.next_run(datetime.now(UTC))
            await asyncio.sleep(max(0.0, (self._next_run_at - datetime.now(UTC)).total_seconds()))
            try:
                await self.run()
            except Exception as exc:  # nouvel essai la nuit suivante
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Maintenance impossible")

    async def run(self, now: datetime | None = None) -> MaintenanceRun:
        """Une maintenance complète (une seule à la fois)."""
        async with self._lock:
            complete = self._aggregator.status().complete_until if self._aggregator else None
            retention = await asyncio.to_thread(load_retention, self._database)
            run = await asyncio.to_thread(self._run, now or datetime.now(UTC), retention, complete)
            self._last_run, self._last_error = run, None
            logger.info(
                "Maintenance : %s journées de brut supprimées, agrégats supprimés %s (%.1f s)",
                len(run.removed_days),
                run.removed_aggregates,
                run.duration_s,
            )
            return run

    def status(self) -> MaintenanceStatus:
        return MaintenanceStatus(
            running=self._task is not None,
            in_progress=self._lock.locked(),
            next_run_at=self._next_run_at,
            last_run=self._last_run,
            last_error=self._last_error,
            retention=load_retention(self._database),
            disk=DiskUsage(
                raw_bytes=directory_size(self._raw.root),
                graph_bytes=directory_size(self._data_dir / GRAPH_DIRNAME),
                database_bytes=sum(
                    directory_size(self._data_dir / f"{DATABASE_FILENAME}{suffix}")
                    for suffix in ("", "-wal", "-shm")
                ),
            ),
        )

    # --- Travail (dans un fil à part) --------------------------------------------------------

    def _run(
        self,
        now: datetime,
        retention: Retention,
        complete: dict[str, datetime] | None,
    ) -> MaintenanceRun:
        began = time_module.monotonic()
        zone = self._raw.zone
        today = now.astimezone(zone).date()
        run = MaintenanceRun(started_at=now, duration_s=0.0)
        # Agrégée jusqu'où : la plus en retard des périodes (inconnue juste après un démarrage).
        aggregated = min(complete.values()) if complete and set(complete) == set(PERIODS) else None
        for day in self._raw.days():
            if day >= today - timedelta(days=retention.raw_days):
                continue
            day_end = next_midnight(datetime.combine(day, time(12), zone), zone)
            if self._aggregator is not None and (aggregated is None or aggregated < day_end):
                run.kept_days.append(day)
                continue
            self._raw.remove_day(day)
            run.removed_days.append(day)
        for period, days in ((QUARTER, retention.quarter_days), (HOUR, retention.hour_days)):
            if days is not None:
                cutoff = datetime.combine(today - timedelta(days=days), time(), zone)
                run.removed_aggregates[period] = self._prune(period, cutoff.astimezone(UTC))
        self._graph.optimize()
        run.duration_s = round(time_module.monotonic() - began, 1)
        return run

    def _prune(self, period: str, cutoff: datetime) -> int:
        """Supprime les agrégats d'une période antérieurs à ``cutoff``, capteur par capteur."""
        zone = self._raw.zone
        removed = 0
        for graph in self._graph.named_graphs(f"{BASE}/graph/aggregates/{period}/"):
            month = date.fromisoformat(graph.rsplit("/", 1)[1] + "-01")
            if datetime.combine(month, time(), zone) >= cutoff:
                continue  # mois entièrement conservé
            sensors = [
                row["s"]
                for row in self._graph.select(
                    f"SELECT DISTINCT ?s WHERE {{ GRAPH <{graph}> "
                    f"{{ ?a <{SOSA}madeBySensor> ?s }} }}"
                )
            ]
            for sensor in sensors:
                expired = (
                    f"?a <{SOSA}madeBySensor> <{sensor}> ; <{VOCAB}start> ?t . "
                    f"FILTER(?t < {_xsd(cutoff)})"
                )
                for row in self._graph.select(
                    f"SELECT (COUNT(?a) AS ?n) WHERE {{ GRAPH <{graph}> {{ {expired} }} }}"
                ):
                    removed += int(row["n"])
                self._graph.update(
                    f"DELETE {{ GRAPH <{graph}> {{ ?a ?p ?o }} }} "
                    f"WHERE {{ GRAPH <{graph}> {{ {expired} ?a ?p ?o }} }}"
                )
            if not any(
                True
                for _ in self._graph.select(
                    f"SELECT ?a WHERE {{ GRAPH <{graph}> {{ ?a ?p ?o }} }} LIMIT 1"
                )
            ):
                self._graph.remove_graph(graph)
        return removed
