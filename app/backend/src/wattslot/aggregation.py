"""Agrégats au quart d'heure et à l'heure (lot 1.3).

Pour chaque entité suivie et chaque période close :

- compteur d'énergie : énergie de la période (kWh), par différence des relevés ; une baisse de
  plus de 10 % est une remise à zéro (compteur quotidien, compteur remplacé), une baisse plus
  faible est ignorée ;
- autres mesures (puissance, état de charge) : moyenne pondérée par la durée et maximum.

Les agrégats sont calculés à partir des relevés bruts déjà écrits, pas du flux en mémoire : un
redémarrage ou une reprise après coupure (lot 1.2) ne laisse pas de période fausse. Le dernier
relevé connu avant une période y est reporté (une puissance constante n'envoie aucun changement).
L'état de l'agrégation (prochaine période, valeur reportée) est gardé en base.

Périodes alignées sur l'heure locale de la maison. Stockage dans le magasin principal, un graphe
nommé par période et par mois (organisation retenue par le banc du lot 0.5) ::

    <agg> a wattslot:Aggregate ;
        sosa:madeBySensor <capteur du modèle de la maison> ;
        wattslot:period "PT15M" ;  # ou "PT1H"
        wattslot:start "…Z"^^xsd:dateTime ;
        wattslot:energyKwh "…"^^xsd:double .  # compteurs ; wattslot:mean, wattslot:max et
                                                # wattslot:last pour les autres mesures
                                                # (wattslot:last : valeur en fin de période)
"""

import asyncio
import logging
import sqlite3
import time as time_module
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from wattslot import history
from wattslot.corrections import CorrectionStore, apply
from wattslot.detection import ENERGY_ROLES, Role, slug
from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.ingestion import Ingestor, Target
from wattslot.ontology import BASE, HOME, VOCAB
from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import SOSA, XSD, RawStores

logger = logging.getLogger(__name__)

QUARTER = "PT15M"
HOUR = "PT1H"
PERIODS = {QUARTER: timedelta(minutes=15), HOUR: timedelta(hours=1)}
GRACE = timedelta(minutes=1)  # relevés encore en file (lots de 5 s), horodatages de HA en retard
INTERVAL_S = 60.0
CATCH_UP_MAX = timedelta(days=3)  # conservation du brut : rien à relire au-delà
RESET_RATIO = 0.9
DECIMALS = 6  # efface le bruit des calculs en virgule flottante (0.2900000000008731)
# Reprise de l'historique : agrégats par chargement en masse, plusieurs entités à la fois. Chaque
# écriture dans RocksDB est recompactée avec une part du magasin qui croît avec lui : par 5 000
# agrégats (une écriture par entité et par tranche), la reprise écrivait 23 fois le volume stocké
# (banc ``dev/tools/bench_import.py``, 1,27 million d'agrégats : 51 Go pour 2,2 Go). Par 100 000 :
# 8,9 Go. Le chargeur en masse prend environ 0,9 Mo de mémoire par millier de quadruplets (6 à 7
# par agrégat) : 360 Mo de plus au plus fort de la reprise.
IMPORT_BATCH = 100_000
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


@dataclass(frozen=True)
class Carry:
    """Dernier relevé connu avant une période."""

    time: datetime
    value: float


@dataclass(frozen=True)
class Values:
    energy_kwh: float | None = None
    mean: float | None = None
    maximum: float | None = None
    last: float | None = None  # valeur en fin de période (le SoC à la fin de l'heure)


class Aggregate(BaseModel):
    entity_id: str
    period: str
    start: datetime
    energy_kwh: float | None = None
    mean: float | None = None
    max: float | None = None
    last: float | None = None


class HistoryStatus(BaseModel):
    """Reprise de l'historique de HA, par entité suivie."""

    imported: int = 0  # entités reprises
    pending: list[str] = []  # pas encore reprises (après le premier calcul sur le brut)
    without_statistics: list[str] = []  # sans statistiques dans HA (pas de state_class)
    since: dict[str, datetime] = {}  # par période : agrégat repris le plus ancien


class AggregationStatus(BaseModel):
    running: bool
    last_run_at: datetime | None = None
    written: int = 0  # agrégats écrits depuis le démarrage
    complete_until: dict[str, datetime] = {}  # par période : fin de la dernière période calculée
    last_error: str | None = None
    history: HistoryStatus = HistoryStatus()


def period_start(moment: datetime, length: timedelta, zone: ZoneInfo) -> datetime:
    """Début (UTC) de la période qui contient ``moment``, alignée sur l'heure locale."""
    local = moment.astimezone(zone)
    minutes = int(length.total_seconds() // 60)
    minute = (local.minute // minutes) * minutes if minutes < 60 else 0
    return local.replace(minute=minute, second=0, microsecond=0).astimezone(UTC)


def next_midnight(moment: datetime, zone: ZoneInfo) -> datetime:
    day = moment.astimezone(zone).date() + timedelta(days=1)
    return datetime.combine(day, time(), zone).astimezone(UTC)


def graph_iri(period: str, start: datetime, zone: ZoneInfo) -> str:
    return f"{BASE}/graph/aggregates/{period}/{start.astimezone(zone):%Y-%m}"


def months(start: datetime, end: datetime, zone: ZoneInfo) -> list[date]:
    first = start.astimezone(zone).date().replace(day=1)
    last = (end - timedelta(microseconds=1)).astimezone(zone).date()
    found, current = [], first
    while current <= last:
        found.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return found


def compute(
    role: Role,
    start: datetime,
    end: datetime,
    carry: Carry | None,
    points: list[tuple[datetime, float]],
) -> tuple[Values | None, Carry | None]:
    """Agrégat d'une période (``points`` triés, tous dans la période) et valeur à reporter."""
    out = Carry(*points[-1]) if points else carry
    if role in ENERGY_ROLES:
        base = carry.value if carry else None
        energy = 0.0
        for _, value in points:
            if base is None or value >= base:
                energy += 0.0 if base is None else value - base
                base = value
            elif value < base * RESET_RATIO:
                energy += value  # remise à zéro
                base = value
        return (Values(energy_kwh=energy) if base is not None else None), out
    current = carry.value if carry else None
    since = start if carry else None
    integral = covered = 0.0
    maximum = current
    for moment, value in points:
        if current is not None and since is not None:
            seconds = (moment - since).total_seconds()
            integral += current * seconds
            covered += seconds
        current, since = value, moment
        maximum = value if maximum is None else max(maximum, value)
    if current is None or since is None:
        return None, out
    seconds = (end - since).total_seconds()
    integral += current * seconds
    covered += seconds
    mean = integral / covered if covered > 0 else current
    return Values(mean=mean, maximum=maximum, last=current), out


def aggregate_nquads(
    entity_id: str, target: Target, period: str, start: datetime, values: Values, graph: str
) -> str:
    node = f"<{HOME}agg/{period}/{slug(entity_id)}/{int(start.timestamp())}>"
    when = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    g = f"<{graph}>"
    lines = [
        f"{node} <{RDF_TYPE}> <{VOCAB}Aggregate> {g} .",
        f"{node} <{SOSA}madeBySensor> <{target.sensor_iri}> {g} .",
        f'{node} <{VOCAB}period> "{period}" {g} .',
        f'{node} <{VOCAB}start> "{when}"^^<{XSD}dateTime> {g} .',
    ]
    for name, value in (
        ("energyKwh", values.energy_kwh),
        ("mean", values.mean),
        ("max", values.maximum),
        ("last", values.last),
    ):
        if value is not None:
            rounded = round(value, DECIMALS) + 0.0  # + 0.0 : pas de « -0.0 »
            lines.append(f'{node} <{VOCAB}{name}> "{rounded!r}"^^<{XSD}double> {g} .')
    return "\n".join(lines) + "\n"


class Aggregator:
    def __init__(
        self,
        ingestor: Ingestor,
        raw: RawStores,
        graph: GraphStore,
        database: sqlite3.Connection,
        client: HomeAssistantClient | None = None,
    ) -> None:
        self._ingestor = ingestor
        self._client = client
        self._raw = raw
        self._graph = graph
        self._database = database
        self._corrections = CorrectionStore(database)
        self._task: asyncio.Task[None] | None = None
        self._status = AggregationStatus(running=False)
        # Reprise de l'historique : agrégats en attente du chargement en masse (N-Quads, un par
        # élément) et entités reprises, notées dans ``history_import`` une fois tous leurs
        # agrégats écrits (fin de leurs agrégats dans la file, résumé). Perdue à l'arrêt : ces
        # entités sont reprises au démarrage suivant, sans doublon (agrégats existants sautés).
        self._spool: list[str] = []
        self._spooled: list[tuple[str, int, dict[str, tuple[int, datetime | None]]]] = []

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        self._status.running = True

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._status.running = False

    async def _loop(self) -> None:
        while True:
            try:
                await self.step()
                # Une entité par tour : le calcul sur le brut n'attend jamais la fin de toute
                # la reprise (1 h 25 pour la maison de référence sur le N150).
                imported = await self.import_history(limit=1)
            except Exception as exc:  # nouvel essai au tour suivant
                self._status.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Agrégation impossible")
                imported = 0
            await asyncio.sleep(0 if imported else INTERVAL_S)

    async def step(self, now: datetime | None = None) -> int:
        """Calcule les périodes closes ; renvoie le nombre d'agrégats écrits."""
        if self._ingestor.backfilling:
            return 0
        targets = self._ingestor.targets
        if not targets:
            return 0
        moment = now or datetime.now(UTC)
        written = await asyncio.to_thread(self._aggregate, targets, moment)
        self._status.written += written
        self._status.last_run_at = datetime.now(UTC)
        self._status.last_error = None
        return written

    def status(self) -> AggregationStatus:
        status = self._status.model_copy(deep=True)
        status.history = self._history_status()
        return status

    # --- Calcul (dans un fil à part) ---------------------------------------------------------

    def _state(self) -> dict[tuple[str, str], tuple[datetime, Carry | None]]:
        rows = self._database.execute(
            "SELECT entity_id, period, next_start, carry_time, carry_value FROM aggregation_state"
        )
        return {
            (entity_id, period): (
                datetime.fromisoformat(next_start),
                Carry(datetime.fromisoformat(carry_time), carry_value)
                if carry_time is not None and carry_value is not None
                else None,
            )
            for entity_id, period, next_start, carry_time, carry_value in rows
        }

    def _earliest(self, zone: ZoneInfo) -> datetime | None:
        days = self._raw.days()
        if not days:
            return None
        return datetime.combine(days[0], time(), zone).astimezone(UTC)

    def _aggregate(self, targets: dict[str, Target], now: datetime) -> int:
        zone = self._raw.zone
        earliest = self._earliest(zone)
        if earliest is None:
            return 0
        state = self._state()
        written = 0
        for period, length in PERIODS.items():
            ready = period_start(now - GRACE, length, zone)  # périodes closes avant cette heure
            floor = period_start(max(earliest, ready - CATCH_UP_MAX), length, zone)
            cursors: dict[str, datetime] = {}
            carries: dict[str, Carry | None] = {}
            for entity_id in targets:
                next_start, carry = state.get((entity_id, period), (floor, None))
                if next_start < floor:  # coupure plus longue que la conservation du brut
                    next_start, carry = floor, None
                cursors[entity_id], carries[entity_id] = next_start, carry
            chunk_start = min(cursors.values())
            if chunk_start >= ready and any((e, period) not in state for e in targets):
                # Aucune période close depuis le début du brut (première heure après minuit) :
                # les curseurs sont enregistrés tout de suite, pour que la reprise de
                # l'historique de HA n'attende pas la fin de la première période.
                self._save(period, targets, cursors, carries)
            while chunk_start < ready:
                chunk_end = min(ready, next_midnight(chunk_start, zone))
                written += self._chunk(
                    targets, period, length, chunk_start, chunk_end, cursors, carries
                )
                chunk_start = chunk_end
            self._status.complete_until[period] = min(cursors.values())
        return written

    def _chunk(
        self,
        targets: dict[str, Target],
        period: str,
        length: timedelta,
        chunk_start: datetime,
        chunk_end: datetime,
        cursors: dict[str, datetime],
        carries: dict[str, Carry | None],
    ) -> int:
        """Une journée (au plus) de périodes : une lecture du brut, une écriture d'agrégats."""
        zone = self._raw.zone
        by_sensor: dict[str, list[tuple[datetime, float]]] = {}
        for sensor_iri, moment, value in self._raw.readings(chunk_start, chunk_end):
            by_sensor.setdefault(sensor_iri, []).append((moment, value))
        nquads: list[str] = []
        for entity_id, target in targets.items():
            start = max(cursors[entity_id], chunk_start)
            if start >= chunk_end:
                continue
            points = sorted(by_sensor.get(target.sensor_iri, []))
            times = [moment for moment, _ in points]
            carry = carries[entity_id]
            while start < chunk_end:
                end = start + length
                inside = points[bisect_left(times, start) : bisect_left(times, end)]
                values, carry = compute(target.role, start, end, carry, inside)
                if values is not None:
                    graph = graph_iri(period, start, zone)
                    nquads.append(aggregate_nquads(entity_id, target, period, start, values, graph))
                start = end
            cursors[entity_id], carries[entity_id] = start, carry
        if nquads:
            self._graph.add_nquads("".join(nquads), deferred=True)
        self._save(period, targets, cursors, carries)
        return len(nquads)

    def _save(
        self,
        period: str,
        targets: Iterable[str],
        cursors: dict[str, datetime],
        carries: dict[str, Carry | None],
    ) -> None:
        rows = [
            (
                entity_id,
                period,
                cursors[entity_id].isoformat(),
                carry.time.isoformat() if (carry := carries[entity_id]) else None,
                carry.value if carry else None,
            )
            for entity_id in targets
        ]
        with self._database:
            self._database.executemany(
                "INSERT INTO aggregation_state VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(entity_id, period) DO UPDATE SET next_start = excluded.next_start, "
                "carry_time = excluded.carry_time, carry_value = excluded.carry_value",
                rows,
            )

    # --- Reprise de l'historique de HA (``history.py``) ---------------------------------------

    async def import_history(self, limit: int | None = None) -> int:
        """Reprend les statistiques de HA des entités pas encore reprises ; renvoie leur nombre.

        ``limit`` : nombre d'entités au plus pour cet appel (toutes par défaut).

        Après au moins un calcul sur le brut : seules les périodes antérieures à la prochaine
        période à calculer, et pas déjà calculées, sont reprises.

        Les agrégats sont écrits par ``IMPORT_BATCH``, plusieurs entités à la fois, et le reste
        quand plus aucune entité n'attend : une entité reprise n'est visible qu'une fois écrite.
        """
        client = self._client
        if client is None or client.status.state is not ConnectionState.CONNECTED:
            return 0
        targets = self._ingestor.targets
        done = await asyncio.to_thread(self._imported)
        done |= {entity_id for entity_id, _, _ in self._spooled}
        state = await asyncio.to_thread(self._state)

        def ready(entity_id: str) -> bool:
            return entity_id not in done and all((entity_id, p) in state for p in PERIODS)

        count = 0
        for entity_id, target in targets.items():
            if limit is not None and count >= limit:
                break
            if not ready(entity_id):
                continue
            began = time_module.monotonic()
            summary: dict[str, tuple[int, datetime | None]] = {}
            for period, length in PERIODS.items():
                lines, summary[period] = await self._import_period(
                    client, entity_id, target, period, length, state[(entity_id, period)][0]
                )
                self._spool.extend(lines)
            self._spooled.append((entity_id, len(self._spool), summary))
            done.add(entity_id)
            count += 1
            logger.info(
                "Historique de HA repris pour %s : %s quarts d'heure, %s heures (%.1f s)",
                entity_id,
                summary[QUARTER][0],
                summary[HOUR][0],
                time_module.monotonic() - began,
            )
            while len(self._spool) >= IMPORT_BATCH:
                await asyncio.to_thread(self._write_spool, IMPORT_BATCH)
        if self._spooled and not any(ready(entity_id) for entity_id in targets):
            await asyncio.to_thread(self._write_spool, len(self._spool))  # dernières entités
        return count

    async def _import_period(
        self,
        client: HomeAssistantClient,
        entity_id: str,
        target: Target,
        period: str,
        length: timedelta,
        before: datetime,
    ) -> tuple[list[str], tuple[int, datetime | None]]:
        """Agrégats d'une période à reprendre (N-Quads, un par élément), leur nombre et le plus
        ancien."""
        zone = self._raw.zone
        counter = target.role in ENERGY_ROLES
        rows = await history.statistics(client, entity_id, period, before, counter)
        grouped = history.group(rows, counter, lambda m: period_start(m, length, zone), before)
        if not grouped:
            return [], (0, None)
        earliest = min(grouped)
        existing = {
            aggregate.start
            for aggregate in await asyncio.to_thread(
                self.read, entity_id, period, earliest, before, False
            )
        }
        nquads = [
            aggregate_nquads(
                entity_id,
                target,
                period,
                start,
                Values(energy_kwh=energy, mean=mean, maximum=maximum),
                graph_iri(period, start, zone),
            )
            for start, (energy, mean, maximum) in sorted(grouped.items())
            if start not in existing
        ]
        return nquads, (len(nquads), earliest)

    def _write_spool(self, count: int) -> None:
        """Écrit les ``count`` premiers agrégats en attente (un seul chargement en masse), puis
        note les entités dont tous les agrégats sont écrits."""
        began = time_module.monotonic()
        batch = self._spool[:count]
        del self._spool[:count]
        if batch:
            written = len(batch)
            self._graph.bulk_add_nquads(batch)  # vidée pendant le chargement
            self._status.written += written
            logger.info(
                "Historique de HA : %s agrégats écrits (%.1f s)",
                written,
                time_module.monotonic() - began,
            )
        spooled, self._spooled = self._spooled, []
        for entity_id, end, summary in spooled:
            if end <= count:
                self._record_import(entity_id, summary)
            else:
                self._spooled.append((entity_id, end - count, summary))

    def _imported(self) -> set[str]:
        return {row[0] for row in self._database.execute("SELECT entity_id FROM history_import")}

    def _record_import(
        self, entity_id: str, summary: dict[str, tuple[int, datetime | None]]
    ) -> None:
        quarters, quarter_since = summary[QUARTER]
        hours, hour_since = summary[HOUR]
        with self._database:
            self._database.execute(
                "INSERT OR REPLACE INTO history_import VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entity_id,
                    datetime.now(UTC).isoformat(),
                    quarters,
                    quarter_since.isoformat() if quarter_since else None,
                    hours,
                    hour_since.isoformat() if hour_since else None,
                ),
            )
            # Journées du journal des cycles calculées sur des agrégats encore incomplets
            # (« quarters ») : recalculées à la demande avec l'historique repris.
            self._database.execute("DELETE FROM appliance_days WHERE source = 'quarters'")

    def _history_status(self) -> HistoryStatus:
        rows = self._database.execute(
            "SELECT entity_id, quarters, quarter_since, hours, hour_since FROM history_import"
        ).fetchall()
        targets = self._ingestor.targets
        since: dict[str, datetime] = {}
        for _, _, quarter_since, _, hour_since in rows:
            for period, value in ((QUARTER, quarter_since), (HOUR, hour_since)):
                if value is not None:
                    moment = datetime.fromisoformat(value)
                    since[period] = min(since.get(period, moment), moment)
        imported = {row[0] for row in rows}
        return HistoryStatus(
            imported=len(imported & set(targets)),
            pending=sorted(set(targets) - imported),
            without_statistics=sorted(
                entity_id
                for entity_id, quarters, _, hours, _ in rows
                if quarters == 0 and hours == 0 and entity_id in targets
            ),
            since=since,
        )

    # --- Lecture -----------------------------------------------------------------------------

    def read(
        self,
        entity_id: str,
        period: str,
        start: datetime,
        end: datetime,
        corrected: bool = True,
    ) -> list[Aggregate]:
        """Agrégats d'une entité sur ``[start, end)``, triés (graphes nommés explicitement), avec
        les corrections de la qualité des données (``corrections.py``) sauf ``corrected=False``."""
        target = self._ingestor.targets.get(entity_id)
        if target is None or period not in PERIODS:
            return []
        zone = self._raw.zone
        pattern = (
            f"?a <{SOSA}madeBySensor> <{target.sensor_iri}> ; <{VOCAB}start> ?t . "
            f"OPTIONAL {{ ?a <{VOCAB}energyKwh> ?e }} OPTIONAL {{ ?a <{VOCAB}mean> ?m }} "
            f"OPTIONAL {{ ?a <{VOCAB}max> ?x }} OPTIONAL {{ ?a <{VOCAB}last> ?l }}"
        )
        graphs = " UNION ".join(
            f"{{ GRAPH <{BASE}/graph/aggregates/{period}/{month:%Y-%m}> {{ {pattern} }} }}"
            for month in months(start, end, zone)
        )
        low = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        high = end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self._graph.select(
            f"SELECT ?t ?e ?m ?x ?l WHERE {{ {graphs} "
            f'FILTER(?t >= "{low}"^^<{XSD}dateTime> && ?t < "{high}"^^<{XSD}dateTime>) }}'
        )
        found = [
            Aggregate(
                entity_id=entity_id,
                period=period,
                start=datetime.fromisoformat(row["t"]),
                energy_kwh=float(row["e"]) if "e" in row else None,
                mean=float(row["m"]) if "m" in row else None,
                max=float(row["x"]) if "x" in row else None,
                last=float(row["l"]) if "l" in row else None,
            )
            for row in rows
        ]
        found.sort(key=lambda aggregate: aggregate.start)
        if not corrected:
            return found
        return apply(found, self._corrections.active(entity_id, period, start, end))
