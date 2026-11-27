"""Conservation des données et maintenance nocturne (lot 1.4).

Chaque nuit (``MAINTENANCE_AT``, heure locale de la maison), ou à la demande :

1. **Brut** : suppression des journées échues, dossier par dossier (exigence
   mesurée sur un N150, lot 0.5). Une journée n'est supprimée qu'une fois entièrement agrégée.
2. **Agrégats** : suppression des périodes échues. Un mois entièrement échu est retiré d'un
   bloc, graphe par graphe, avec un seul ``flush`` pour tous : c'est le cas de la première
   maintenance après le passage des heures à 15 mois, qui retire des années d'un coup (banc
   d'un magasin de 1,4 Go, dix mois retirés : 3,2 Go écrits, contre 6,6 Go capteur par
   capteur ; même durée). Le mois entamé est vidé capteur par capteur (règles de mémoire :
   jamais de transaction de plusieurs millions de triplets), avec un seul ``flush`` par graphe :
   un ``flush`` par capteur crée autant de petits fichiers que RocksDB recompacte (2,8 Go écrits
   chaque nuit pour une journée supprimée, rapport du 11/11/2026 ; 14 fois moins avec un seul
   ``flush`` sur un magasin de 2 Go). Un graphe mensuel vidé est retiré.
3. **Compactage** du magasin principal (``optimize``), seulement si un graphe mensuel a été
   retiré (une fois par mois avec les réglages par défaut). Le compactage réécrit tout le magasin
   (3,5 Go écrits chaque nuit pour un magasin de 3,4 Go, rapport du 09/11/2026) ; les petites
   suppressions de chaque nuit (une journée de quarts d'heure) sont mêlées aux écritures du jour
   et rendues par les compactages ordinaires de RocksDB, alors qu'un mois retiré occupe une plage
   de clés que plus rien n'écrit (index par graphe) et n'est rendu que par ``optimize``.

Durées de conservation réglables (``retention.py``) : brut 3 jours, quarts d'heure 35 jours,
heures 15 mois.
"""

import asyncio
import logging
import sqlite3
import time as time_module
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from pydantic import BaseModel

from wattslot import memory
from wattslot.aggregation import HOUR, PERIODS, QUARTER, Aggregator, next_midnight
from wattslot.ontology import BASE, VOCAB
from wattslot.retention import Retention, cutoff, load_retention, save_retention
from wattslot.storage.database import DATABASE_FILENAME
from wattslot.storage.graph import GRAPH_DIRNAME, GraphStore
from wattslot.storage.raw import SOSA, XSD, RawStores

__all__ = ["Retention", "load_retention", "save_retention"]  # repris par les appelants

logger = logging.getLogger(__name__)

MAINTENANCE_AT = time(3, 30)  # heure locale, en dehors des heures de production


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
    compacted: bool = False  # magasin compacté : au moins un graphe mensuel retiré
    # Mémoire utilisée gagnée par étape (octets, ``memory.heap_used``), vide hors de glibc : la
    # mémoire montait d'environ 30 Mo à chaque maintenance sur une installation réelle (20/11/2026).
    heap_used_steps: dict[str, int] = {}


STEP_LABELS = {"raw": "brut", QUARTER: "quarts d'heure", HOUR: "heures", "optimize": "compactage"}


class MaintenanceStatus(BaseModel):
    running: bool
    in_progress: bool = False
    next_run_at: datetime | None = None
    last_run: MaintenanceRun | None = None
    last_error: str | None = None
    retention: Retention
    disk: DiskUsage


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


def _steps_text(steps: dict[str, int]) -> str:
    """Mémoire utilisée gagnée par étape, pour le journal ; rien si elle est inconnue."""
    if not steps:
        return ""
    parts = [
        f"{STEP_LABELS.get(name, name)} {value / 1e6:+.0f} Mo" for name, value in steps.items()
    ]
    return " ; mémoire utilisée : " + ", ".join(parts)


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
                "Maintenance : %s journées de brut supprimées, agrégats supprimés %s (%.1f s)%s",
                len(run.removed_days),
                run.removed_aggregates,
                run.duration_s,
                _steps_text(run.heap_used_steps),
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
        used = memory.heap_used()

        def step(name: str) -> None:
            nonlocal used
            current = memory.heap_used()
            if current is not None and used is not None:
                run.heap_used_steps[name] = current - used
            used = current

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
        step("raw")
        removed_graphs = 0
        for period, days in ((QUARTER, retention.quarter_days), (HOUR, retention.hour_days)):
            limit = cutoff(days, today, zone)
            if limit is not None:
                removed, graphs = self._prune(period, limit)
                run.removed_aggregates[period] = removed
                removed_graphs += graphs
                step(period)
        if removed_graphs:
            self._graph.optimize()
            run.compacted = True
            step("optimize")
        run.duration_s = round(time_module.monotonic() - began, 1)
        return run

    def _prune(self, period: str, cutoff: datetime) -> tuple[int, int]:
        """Supprime les agrégats d'une période antérieurs à ``cutoff`` : les mois entièrement
        échus d'un bloc, le mois entamé capteur par capteur ; rend le nombre d'agrégats supprimés
        et celui des graphes mensuels retirés."""
        zone = self._raw.zone
        removed = graphs_removed = 0
        partial = []
        for graph in self._graph.named_graphs(f"{BASE}/graph/aggregates/{period}/"):
            month = date.fromisoformat(graph.rsplit("/", 1)[1] + "-01")
            if datetime.combine(month, time(), zone) >= cutoff:
                continue  # mois entièrement conservé
            following = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            if datetime.combine(following, time(), zone) > cutoff:
                partial.append(graph)
                continue
            for row in self._graph.select(
                f"SELECT (COUNT(?a) AS ?n) WHERE {{ GRAPH <{graph}> {{ ?a <{VOCAB}start> ?t }} }}"
            ):
                removed += int(row["n"])
            self._graph.remove_graph(graph, flush=False)
            graphs_removed += 1
        if graphs_removed:
            self._graph.flush()
        for graph in partial:
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
                    f"WHERE {{ GRAPH <{graph}> {{ {expired} ?a ?p ?o }} }}",
                    flush=False,
                )
            self._graph.flush()
            if not any(
                True
                for _ in self._graph.select(
                    f"SELECT ?a WHERE {{ GRAPH <{graph}> {{ ?a ?p ?o }} }} LIMIT 1"
                )
            ):
                self._graph.remove_graph(graph)
                graphs_removed += 1
        return removed, graphs_removed
