"""Ingestion en temps réel des entités qui ont un rôle dans le modèle de la maison (lot 1.2).

- Abonnement ``subscribe_entities`` de Home Assistant : état complet à l'abonnement (``a``),
  puis différences (``c``) ; horodatage ``lu`` (dernière mise à jour) ou ``lc`` (dernier
  changement). Rétabli par le client à chaque reconnexion.
- Unités normalisées : kWh pour l'énergie, W pour la puissance.
- Filtre : une puissance n'est écrite que si elle varie nettement ou au moins une fois par
  minute ; un compteur, au plus une fois par minute sauf remise à zéro. Mesure de l'effet sur le
  volume par le banc du lot 0.5 : la puissance toutes les 15 s représentait 70 % du brut.
- File d'attente écrite par lots, dans le magasin du jour (``storage/raw.py``).

- Reprise après une coupure : l'heure du dernier relevé écrit par entité est gardée en base ;
  à chaque (re)connexion, l'historique de HA (``history/history_during_period``) comble
  le trou, dans la limite de la conservation du brut (``BACKFILL_MAX``).
"""

import asyncio
import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

from pydantic import BaseModel

from wattslot.detection import ENERGY_ROLES, POWER_ROLES, Role
from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.home_model import HomeModel, sensor_iri
from wattslot.storage.raw import RawStores, Reading

logger = logging.getLogger(__name__)

SUBSCRIPTION = "ingestion"
# Écritures disque (dev/tools/bench_writes.py) : un lot toutes les 30 s (5 s auparavant) et
# l'état de reprise en base toutes les 5 minutes ; une reprise qui relit quelques minutes
# de trop est sans effet (identifiants d'observation déterministes).
BATCH_INTERVAL_S = 30.0
STATE_INTERVAL = timedelta(minutes=5)
BATCH_MAX = 2000
MIN_INTERVAL_S = 60.0  # au moins un relevé par minute, au plus un par minute (compteurs)
POWER_DEADBAND_W = 10.0
POWER_DEADBAND_RATIO = 0.05
BACKFILL_MAX = timedelta(days=3)  # conservation du brut

ENERGY_FACTORS = {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0}
POWER_FACTORS = {"W": 1.0, "kW": 1000.0}


@dataclass(frozen=True)
class Target:
    entity_id: str
    sensor_iri: str
    role: Role
    device: str | None = None  # clé de l'équipement


def targets(model: HomeModel) -> dict[str, Target]:
    """Entités suivies : celles qui ont un rôle dans le modèle (la première occurrence)."""
    found: dict[str, Target] = {}
    for device in model.devices:
        for sensor in device.sensors:
            found.setdefault(
                sensor.entity_id,
                Target(
                    sensor.entity_id,
                    sensor_iri(device.key, sensor.entity_id),
                    sensor.role,
                    device.key,
                ),
            )
    return found


def normalize(role: Role, raw: Any, unit: str | None) -> float | None:
    """Valeur numérique dans l'unité de l'application ; None si inutilisable."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None  # « unavailable », « unknown »…
    if not math.isfinite(value):
        return None
    if role in ENERGY_ROLES:
        factor = ENERGY_FACTORS.get(unit or "kWh")
    elif role in POWER_ROLES:
        factor = POWER_FACTORS.get(unit or "W")
    else:
        factor = 1.0
    return None if factor is None else value * factor


@dataclass
class _Last:
    value: float
    time: datetime


class ReadingFilter:
    """Décide quels relevés écrire, entité par entité."""

    def __init__(self) -> None:
        self._last: dict[str, _Last] = {}

    def keep(self, role: Role, entity_id: str, value: float, time: datetime) -> bool:
        last = self._last.get(entity_id)
        if last is None or time < last.time:
            keep = last is None
        else:
            elapsed = (time - last.time).total_seconds()
            if role in POWER_ROLES:
                deadband = max(POWER_DEADBAND_W, abs(last.value) * POWER_DEADBAND_RATIO)
                keep = abs(value - last.value) >= deadband or elapsed >= MIN_INTERVAL_S
            elif role in ENERGY_ROLES:
                reset = value < last.value
                keep = reset or (value != last.value and elapsed >= MIN_INTERVAL_S)
            else:
                keep = value != last.value or elapsed >= MIN_INTERVAL_S
        if keep:
            self._last[entity_id] = _Last(value, time)
        return keep


class EntityStatus(BaseModel):
    entity_id: str
    role: Role
    device: str | None = None  # clé de l'équipement
    last_value: float | None = None
    last_time: datetime | None = None
    # Dernier signe de vie : relevé reçu, ou ``last_reported`` de l'instantané de HA. HA ne
    # renvoie pas aux abonnés une valeur inchangée (prise à 0 W, compteur à l'arrêt) : sans
    # lui, un capteur stable passait pour muet.
    last_seen: datetime | None = None
    received: int = 0  # relevés reçus de HA
    kept: int = 0  # relevés retenus par le filtre (écrits ou en file)


class IngestionStatus(BaseModel):
    running: bool
    entities: list[EntityStatus]
    received: int
    written: int
    pending: int
    last_batch_at: datetime | None = None
    last_error: str | None = None
    days: list[str] = []
    backfilled: int = 0  # relevés repris de l'historique de HA après une coupure
    last_backfill_at: datetime | None = None


SILENT_AFTER = timedelta(days=1)
STUCK_POWER_W = 1.0  # en dessous : appareil au repos, pas un relevé figé


def silent_entities(
    status: IngestionStatus | None, today: dict[str, int], now: datetime
) -> list[str]:
    """Entités sans relevé aujourd'hui ni signe de vie depuis un jour, dont la valeur figée est
    suspecte.

    HA ne réécrit pas une valeur MQTT inchangée (ni ``last_reported``) : une prise à 0 W au repos
    et une prise morte figée à 0 W sont indiscernables. Ne sont donc retenus que : aucune valeur
    connue ; une puissance non nulle figée ; un compteur figé alors que la puissance du même
    équipement est non nulle ; un autre rôle (état de charge) figé. Une prise débranchée est
    signalée « indisponible » par ailleurs."""
    if status is None:
        return []
    running = {
        e.device
        for e in status.entities
        if e.role in POWER_ROLES and e.last_value is not None and abs(e.last_value) >= STUCK_POWER_W
    }
    found = []
    for entity in status.entities:
        if today.get(entity.entity_id, 0) > 0:
            continue
        last = entity.last_seen or entity.last_time
        if last is not None and now - last <= SILENT_AFTER:
            continue
        value = entity.last_value
        if value is None or last is None:
            suspect = True
        elif entity.role in POWER_ROLES:
            suspect = abs(value) >= STUCK_POWER_W
        elif entity.role in ENERGY_ROLES:
            suspect = entity.device is not None and entity.device in running
        else:
            suspect = True
        if suspect:
            found.append(entity.entity_id)
    return found


@dataclass
class _Counters:
    received: int = 0
    written: int = 0
    last_batch_at: datetime | None = None
    last_error: str | None = None
    backfilled: int = 0
    last_backfill_at: datetime | None = None
    entities: dict[str, EntityStatus] = field(default_factory=dict)


def _timestamp(change: dict[str, Any]) -> datetime | None:
    stamp = change.get("lu", change.get("lc"))
    if stamp is None:
        return None
    return datetime.fromtimestamp(float(stamp), tz=UTC)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        time = datetime.fromisoformat(value)
    except ValueError:
        return None
    return time if time.tzinfo is not None else time.replace(tzinfo=UTC)


class Ingestor:
    def __init__(
        self,
        client: HomeAssistantClient,
        stores: RawStores,
        database: sqlite3.Connection | None = None,
    ) -> None:
        self._client = client
        self._stores = stores
        self._database = database
        self._targets: dict[str, Target] = {}
        self._units: dict[str, str | None] = {}
        self._filter = ReadingFilter()
        self._queue: list[Reading] = []
        self._counters = _Counters()
        self._writer: asyncio.Task[None] | None = None
        self._backfill_task: asyncio.Task[None] | None = None
        # Session de HA dont le trou de coupure est comblé (``None`` : aucune encore).
        self._synced_session: int | None = None
        self._state: dict[str, Reading] = {}  # dernier relevé écrit, pas encore en base
        self._state_saved_at: datetime | None = None

    async def start(self, model: HomeModel) -> None:
        self._client.on_connected(self._on_connected)
        self._writer = asyncio.create_task(self._write_loop())
        await self.reload(model)
        if self._client.status.state is ConnectionState.CONNECTED:
            await self._on_connected()  # déjà connecté : le rappel ne viendra qu'à la prochaine

    async def _on_connected(self) -> None:
        # Journées découpées en heure locale de la maison (fuseau de HA).
        session = self._client.sessions
        time_zone = self._client.snapshot.config.get("time_zone")
        if time_zone:
            try:
                self._stores.set_time_zone(time_zone)
            except (ZoneInfoNotFoundError, ValueError) as exc:  # fuseau inconnu : pas de blocage
                logger.warning("Fuseau de Home Assistant ignoré (%s) : %s", time_zone, exc)
        if self._database is not None and self._targets:
            self._backfill_task = asyncio.create_task(self._backfill(session))
        else:
            self._synced_session = session

    def _last_written(self) -> dict[str, datetime]:
        assert self._database is not None
        rows = self._database.execute("SELECT entity_id, last_time FROM ingestion_state")
        found = {entity_id: datetime.fromisoformat(time) for entity_id, time in rows}
        for entity_id, reading in self._state.items():
            found[entity_id] = max(found.get(entity_id, reading.time), reading.time)
        return found

    async def _backfill(self, session: int) -> None:
        """Comble, depuis l'historique de HA, le trou laissé par une coupure. Réussie ou non
        (historique illisible : trou perdu), la session est ensuite tenue pour à jour."""
        try:
            await self._fill_gap()
        finally:
            self._synced_session = session

    async def _fill_gap(self) -> None:
        now = datetime.now(UTC)
        last = {
            entity_id: max(time, now - BACKFILL_MAX)
            for entity_id, time in (await asyncio.to_thread(self._last_written)).items()
            if entity_id in self._targets
        }
        if not last:
            return  # Première mise en service : la reprise de l'historique relève du lot 1.3.
        try:
            history = await self._client.command(
                "history/history_during_period",
                start_time=min(last.values()).isoformat(),
                end_time=now.isoformat(),
                entity_ids=sorted(last),
                include_start_time_state=False,
                significant_changes_only=False,
                minimal_response=True,
                no_attributes=True,
            )
        except Exception as exc:  # noqa: BLE001 — l'ingestion continue sans rattrapage
            self._counters.last_error = f"reprise : {type(exc).__name__}: {exc}"
            logger.warning("Reprise de l'historique impossible : %s", exc)
            return
        readings: list[Reading] = []
        for entity_id, states in (history or {}).items():
            target = self._targets.get(entity_id)
            if target is None or entity_id not in last:
                continue
            attributes = (self._client.snapshot.states.get(entity_id) or {}).get("attributes")
            unit = (attributes or {}).get("unit_of_measurement")
            gap_filter = ReadingFilter()
            for state in states:
                time = _timestamp(state)
                value = normalize(target.role, state.get("s"), unit)
                if time is None or value is None or time <= last[entity_id]:
                    continue
                if gap_filter.keep(target.role, entity_id, value, time):
                    readings.append(Reading(entity_id, target.sensor_iri, value, time))
        for start in range(0, len(readings), BATCH_MAX):
            await asyncio.to_thread(self.write_batch, readings[start : start + BATCH_MAX])
        self._counters.backfilled += len(readings)
        self._counters.last_backfill_at = datetime.now(UTC)
        if readings:
            logger.info("Reprise après coupure : %s relevés repris de HA", len(readings))

    async def stop(self) -> None:
        try:
            await self._client.unsubscribe(SUBSCRIPTION)
        except Exception:  # connexion fermée en route… : la file est vidée quand même
            logger.exception("Désabonnement impossible à l'arrêt")
        if self._backfill_task is not None:
            await asyncio.gather(self._backfill_task, return_exceptions=True)
        if self._writer is not None:
            self._writer.cancel()
            await asyncio.gather(self._writer, return_exceptions=True)
        await self._flush_queue()
        await asyncio.to_thread(self.close)

    def close(self) -> None:
        """État de reprise en base et relevés vidés sur disque (arrêt)."""
        self.save_state()
        self._stores.flush()

    async def reload(self, model: HomeModel) -> None:
        """Suit les entités du modèle (au démarrage et à chaque enregistrement de la maison)."""
        self._targets = targets(model)
        self._counters.entities = {
            entity_id: self._counters.entities.get(entity_id)
            or EntityStatus(entity_id=entity_id, role=target.role, device=target.device)
            for entity_id, target in self._targets.items()
        }
        if not self._targets:
            await self._client.unsubscribe(SUBSCRIPTION)
            return
        await self._client.subscribe(
            SUBSCRIPTION,
            "subscribe_entities",
            self.on_event,
            entity_ids=sorted(self._targets),
        )

    def on_event(self, event: dict[str, Any]) -> None:
        for entity_id, state in (event.get("a") or {}).items():
            self._units[entity_id] = (state.get("a") or {}).get("unit_of_measurement")
            self._receive(entity_id, state.get("s"), _timestamp(state))
        for entity_id, diff in (event.get("c") or {}).items():
            additions = diff.get("+") or {}
            unit = (additions.get("a") or {}).get("unit_of_measurement")
            if unit:
                self._units[entity_id] = unit
            if "s" in additions:
                self._receive(entity_id, additions["s"], _timestamp(additions))

    def _receive(self, entity_id: str, raw: Any, time: datetime | None) -> None:
        target = self._targets.get(entity_id)
        if target is None or time is None:
            return
        value = normalize(target.role, raw, self._units.get(entity_id))
        if value is None:
            return
        self._counters.received += 1
        status = self._counters.entities[entity_id]
        status.received += 1
        status.last_value, status.last_time = value, time
        if self._filter.keep(target.role, entity_id, value, time):
            self._queue.append(Reading(entity_id, target.sensor_iri, value, time))
            status.kept += 1

    async def _write_loop(self) -> None:
        while True:
            await asyncio.sleep(BATCH_INTERVAL_S)
            await self._flush_queue()

    async def _flush_queue(self) -> None:
        while self._queue:
            batch, self._queue = self._queue[:BATCH_MAX], self._queue[BATCH_MAX:]
            try:
                written = await asyncio.to_thread(self.write_batch, batch)
            except Exception as exc:  # noqa: BLE001 — le lot est remis en file
                self._queue = batch + self._queue
                self._counters.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Écriture des relevés impossible : %s", exc)
                return
            self._counters.written += written
            self._counters.last_batch_at = datetime.now(UTC)

    def write_batch(self, batch: list[Reading], now: datetime | None = None) -> int:
        """Écrit un lot et retient, par entité, le dernier relevé écrit (reprise) : en base au
        plus toutes les ``STATE_INTERVAL``, et à l'arrêt."""
        written = self._stores.write(batch)
        for reading in batch:
            known = self._state.get(reading.entity_id)
            if known is None or reading.time > known.time:
                self._state[reading.entity_id] = reading
        now = now or datetime.now(UTC)
        if self._state_saved_at is None or now - self._state_saved_at >= STATE_INTERVAL:
            self.save_state(now)
        return written

    def save_state(self, now: datetime | None = None) -> None:
        """Derniers relevés écrits, par entité, en base (point de départ de la reprise)."""
        self._state_saved_at = now or datetime.now(UTC)
        if self._database is None or not self._state:
            self._state = {}
            return
        with self._database:
            self._database.executemany(
                "INSERT INTO ingestion_state (entity_id, last_time, last_value) "
                "VALUES (?, ?, ?) ON CONFLICT(entity_id) DO UPDATE SET "
                "last_time = excluded.last_time, last_value = excluded.last_value "
                "WHERE excluded.last_time > ingestion_state.last_time",
                [(r.entity_id, r.time.isoformat(), r.value) for r in self._state.values()],
            )
        self._state = {}

    @property
    def targets(self) -> dict[str, Target]:
        """Entités suivies (copie)."""
        return dict(self._targets)

    @property
    def ready(self) -> bool:
        """Brut complet jusqu'à maintenant : HA connecté et trou de la dernière coupure comblé.
        L'agrégation attend sinon : au démarrage avant la connexion, pendant une coupure, puis
        pendant la reprise, elle clorait les périodes du trou à vide (0 kWh), et les relevés
        repris ensuite, plus anciens que ses curseurs, ne seraient jamais agrégés."""
        return (
            self._client.status.state is ConnectionState.CONNECTED
            and self._synced_session == self._client.sessions
        )

    def _last_seen(self, status: EntityStatus) -> datetime | None:
        state = self._client.snapshot.states.get(status.entity_id) or {}
        reported = _parse_time(state.get("last_reported") or state.get("last_updated"))
        times = [t for t in (status.last_time, reported) if t is not None]
        return max(times) if times else None

    def status(self) -> IngestionStatus:
        counters = self._counters
        return IngestionStatus(
            running=self._writer is not None and not self._writer.done() and bool(self._targets),
            entities=[
                status.model_copy(update={"last_seen": self._last_seen(status)})
                for status in sorted(counters.entities.values(), key=lambda s: s.entity_id)
            ],
            received=counters.received,
            written=counters.written,
            pending=len(self._queue),
            last_batch_at=counters.last_batch_at,
            last_error=counters.last_error,
            days=[day.isoformat() for day in self._stores.days()],
            backfilled=counters.backfilled,
            last_backfill_at=counters.last_backfill_at,
        )
