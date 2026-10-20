"""Qualité des données (lot qualité, 1/3) : détection des anomalies des compteurs d'énergie et
corrections, rangées à part.

Anomalies cherchées dans les agrégats (``aggregation.py``), heure par heure et quart d'heure
par quart d'heure :

- saut : énergie d'une période au-delà de la limite physique du capteur (un compteur coupé,
  compté comme une remise à zéro, ajoute tout son index : 64 000 kWh en une heure) ;
- valeur négative ;
- trou : périodes sans agrégat entre deux périodes qui en ont.

Limite physique d'une heure : puissance souscrite (achat au réseau, consommation des appareils :
aucun ne tire plus que la maison), puissance des panneaux décrits (production), puissance de la
batterie (charge, décharge), avec une marge ; 36 kVA sans contrat réglé.

Corrections : rangées à part (``corrections.py``) ; ``Aggregator.read`` les applique à la
lecture. Écarter une période la retire des lectures (un
trou, que la consommation de base ignore) ; l'estimer la remplace par la moyenne des périodes
voisines. Chaque correction garde le capteur, la période, la valeur d'origine et la valeur
corrigée : de quoi l'annuler, et plus tard la reporter dans le recorder de HA.

Les sauts et valeurs négatives sont corrigés automatiquement (``automatic``), une fois : une
correction annulée n'est pas refaite. Tant que le relevé brut existe (trois jours), la période est
recalculée sur le brut avec la règle actuelle des remises à zéro (une coupure du capteur n'en est
plus une) ; sinon, ou si le recalcul n'est pas plausible, elle est écartée.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from wattslot import configuration as configuration_module
from wattslot import home_model
from wattslot.aggregation import HOUR, PERIODS, QUARTER, Aggregate
from wattslot.battery_settings import DEFAULT as DEFAULT_BATTERY
from wattslot.configuration import Configuration
from wattslot.corrections import Correction, CorrectionStore, Kind, Method
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeModel
from wattslot.storage.graph import GraphStore

logger = logging.getLogger(__name__)

DEFAULT_CONTRACT_KVA = 36.0  # plus forte puissance souscrite d'un particulier (planning.engine)
MARGIN = 1.2  # marge sur la limite physique (pointes, horodatages décalés)
# En dessous : valeur négative. Au-dessus, l'arrondi des statistiques de HA (-0,01 kWh sur un
# quart d'heure de surplus), pas un compteur qui recule.
NEGATIVE_KWH = -0.05
ESTIMATE_NEIGHBOURS = 3  # périodes voisines, de part et d'autre, pour une estimation
INTERVAL_S = 15 * 60.0  # surveillance automatique
RECENT = timedelta(hours=26)  # surveillance : dernières périodes closes
# Premier passage après le démarrage : les heures de la fenêtre de la consommation de base
# (``planning.past.baseline`` : six semaines et deux de sécurité), les quarts d'heure des
# derniers jours.
FIRST_HOURS = timedelta(weeks=8)
FIRST_QUARTERS = timedelta(days=3)

COUNTERS = {
    Role.ENERGY_PRODUCED,
    Role.ENERGY_IMPORTED,
    Role.ENERGY_EXPORTED,
    Role.ENERGY_CHARGED,
    Role.ENERGY_DISCHARGED,
    Role.ENERGY_CONSUMED,
}


class Anomaly(BaseModel):
    entity_id: str
    device: str  # clé de l'équipement
    period: str
    start: datetime
    kind: Kind
    energy_kwh: float | None = None  # valeur lue (saut, valeur négative)
    limit_kwh: float | None = None  # limite physique de la période (saut)
    missing: int = 0  # périodes manquantes (trou)
    correction: Correction | None = None  # correction en vigueur


# Énergie d'une période recalculée sur le brut (``Aggregator.recompute``), None sans brut.
Recompute = Callable[[str, str, datetime], float | None]


class Reader(Protocol):
    def read(
        self,
        entity_id: str,
        period: str,
        start: datetime,
        end: datetime,
        corrected: bool = True,
    ) -> list[Aggregate]: ...


# --- Limites physiques ------------------------------------------------------------------------


@dataclass(frozen=True)
class Sensor:
    entity_id: str
    device: str
    role: Role
    limit_kwh_per_hour: float


def sensors(home: HomeModel, saved: Configuration) -> list[Sensor]:
    """Compteurs d'énergie de la maison et leur limite physique par heure."""
    contract = (saved.tariff.contract_kva if saved.tariff else None) or DEFAULT_CONTRACT_KVA
    battery = saved.battery or DEFAULT_BATTERY
    capacity = sum(d.capacity_kwh or 0.0 for d in home.devices if d.kind is DeviceKind.BATTERY)
    charge_w, discharge_w = battery.powers_w(capacity) if capacity > 0 else (0.0, 0.0)
    found: dict[str, Sensor] = {}
    for device in home.devices:
        settings = saved.of(device.key)
        panels = settings.panels if settings else None
        peak = sum(array.kwp for array in panels.arrays) if panels else 0.0
        for sensor in device.sensors:
            if sensor.role not in COUNTERS or sensor.entity_id in found:
                continue
            if sensor.role is Role.ENERGY_PRODUCED and peak > 0:
                limit = peak
            elif sensor.role is Role.ENERGY_CHARGED and charge_w > 0:
                limit = charge_w / 1000
            elif sensor.role is Role.ENERGY_DISCHARGED and discharge_w > 0:
                limit = discharge_w / 1000
            else:
                limit = contract
            found[sensor.entity_id] = Sensor(
                sensor.entity_id, device.key, sensor.role, limit * MARGIN
            )
    return list(found.values())


# Mesures horaires du jour gardées avec le plan (``planning.actual``), relues sur le brut.
ACTUAL_SERIES = (
    "production_reelle_horaire",
    "consommation_reelle_horaire",
    "reseau_reel_soutire_horaire",
    "reseau_reel_injecte_horaire",
)


def house_limit_kwh(home: HomeModel, saved: Configuration) -> float:
    """Le plus que la maison peut tirer, produire ou échanger en une heure : réseau,
    panneaux et décharge de la batterie réunis, avec la marge."""
    contract = (saved.tariff.contract_kva if saved.tariff else None) or DEFAULT_CONTRACT_KVA
    peak = sum(
        array.kwp
        for settings in saved.devices
        if settings.panels
        for array in settings.panels.arrays
    )
    capacity = sum(d.capacity_kwh or 0.0 for d in home.devices if d.kind is DeviceKind.BATTERY)
    battery = saved.battery or DEFAULT_BATTERY
    discharge_w = battery.powers_w(capacity)[1] if capacity > 0 else 0.0
    return (contract + peak + discharge_w / 1000) * MARGIN


def plausible_actual(
    content: Mapping[str, Any], limit_kwh: float
) -> tuple[dict[str, Any], list[int]]:
    """Plan gardé dont les mesures horaires impossibles (au-delà de ``limit_kwh``, ou
    négatives) sont écartées, et les heures écartées : une valeur fausse ne cache plus les autres
    dans les vues (graphiques, cartes, totaux)."""
    actual = content.get("donnees_reelles_cache")
    if not isinstance(actual, Mapping):
        return dict(content), []
    discarded: set[int] = set()
    cleaned = dict(actual)
    for key in ACTUAL_SERIES:
        series = actual.get(key)
        if not isinstance(series, Mapping):
            continue
        kept = {}
        for hour, value in series.items():
            if isinstance(value, int | float) and not NEGATIVE_KWH <= value <= limit_kwh:
                discarded.add(int(hour))
            else:
                kept[hour] = value
        cleaned[key] = kept
    return {**content, "donnees_reelles_cache": cleaned}, sorted(discarded)


def hours(period: str) -> float:
    return PERIODS[period].total_seconds() / 3600


# --- Détection -------------------------------------------------------------------------------


def detect(sensor: Sensor, period: str, aggregates: list[Aggregate]) -> list[Anomaly]:
    """Anomalies d'une suite d'agrégats triés d'un compteur, sur une période (agrégats
    d'origine, sans corrections)."""
    limit = sensor.limit_kwh_per_hour * hours(period)
    length = PERIODS[period]

    def anomaly(start: datetime, kind: Kind, **values: float | int) -> Anomaly:
        return Anomaly(
            entity_id=sensor.entity_id,
            device=sensor.device,
            period=period,
            start=start,
            kind=kind,
            **values,  # type: ignore[arg-type]
        )

    found: list[Anomaly] = []
    previous: datetime | None = None
    for aggregate in aggregates:
        if previous is not None:
            missing = int((aggregate.start - previous) / length) - 1
            if missing > 0:
                found.append(anomaly(previous + length, Kind.GAP, missing=missing))
        previous = aggregate.start
        energy = aggregate.energy_kwh
        if energy is None:
            continue
        if energy > limit:
            found.append(anomaly(aggregate.start, Kind.SPIKE, energy_kwh=energy, limit_kwh=limit))
        elif energy < NEGATIVE_KWH:
            found.append(anomaly(aggregate.start, Kind.NEGATIVE, energy_kwh=energy))
    return found


def estimate(
    aggregates: list[Aggregate], start: datetime, period: str, limit: float
) -> float | None:
    """Moyenne des périodes voisines plausibles (au plus ``ESTIMATE_NEIGHBOURS`` de chaque côté),
    ou None sans voisine."""
    length = PERIODS[period]
    values = [
        a.energy_kwh
        for a in aggregates
        if a.start != start
        and abs(a.start - start) <= length * ESTIMATE_NEIGHBOURS
        and a.energy_kwh is not None
        and NEGATIVE_KWH <= a.energy_kwh <= limit
    ]
    return round(sum(values) / len(values), 6) if values else None


# --- Analyse ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scan:
    anomalies: list[Anomaly]
    corrected: int  # corrections automatiques faites par cette analyse


AUTOMATIC = {Kind.SPIKE, Kind.NEGATIVE}


def scan(
    reader: Reader,
    store: CorrectionStore,
    home: HomeModel,
    saved: Configuration,
    periods: dict[str, tuple[datetime, datetime]],
    entity_ids: Iterable[str] | None = None,
    automatic: bool = True,
    recompute: Recompute | None = None,
) -> Scan:
    """Anomalies des compteurs (tous, ou ``entity_ids``) sur chaque période demandée ; les sauts
    et valeurs négatives jamais corrigés le sont si ``automatic`` : recalculés sur le brut quand
    c'est possible et plausible, écartés sinon."""
    wanted = set(entity_ids) if entity_ids is not None else None
    anomalies: list[Anomaly] = []
    corrected = 0
    for sensor in sensors(home, saved):
        if wanted is not None and sensor.entity_id not in wanted:
            continue
        for period, (start, end) in periods.items():
            original = reader.read(sensor.entity_id, period, start, end, corrected=False)
            active = store.active(sensor.entity_id, period, start, end)
            for anomaly in detect(sensor, period, original):
                correction = active.get(anomaly.start)
                if (
                    correction is None
                    and automatic
                    and anomaly.kind in AUTOMATIC
                    and not store.known(sensor.entity_id, period, anomaly.start)
                ):
                    value = (
                        recompute(sensor.entity_id, period, anomaly.start) if recompute else None
                    )
                    limit = sensor.limit_kwh_per_hour * hours(period)
                    if value is not None and NEGATIVE_KWH <= value <= limit:
                        correction = store.add(anomaly, Method.RAW, value, automatic=True)
                    else:
                        correction = store.add(anomaly, Method.DISCARD, None, automatic=True)
                    corrected += 1
                anomalies.append(anomaly.model_copy(update={"correction": correction}))
    anomalies.sort(key=lambda a: (a.start, a.entity_id, a.period))
    return Scan(anomalies, corrected)


def correct(
    reader: Reader,
    store: CorrectionStore,
    home: HomeModel,
    saved: Configuration,
    entity_id: str,
    period: str,
    start: datetime,
    method: Method,
    recompute: Recompute | None = None,
) -> Correction:
    """Correction demandée d'une période d'un compteur ; ``ValueError`` (code) sinon."""
    sensor = next((s for s in sensors(home, saved) if s.entity_id == entity_id), None)
    if sensor is None:
        raise ValueError("unknown_sensor")
    length = PERIODS[period]
    around = length * (ESTIMATE_NEIGHBOURS + 1)
    original = reader.read(entity_id, period, start - around, start + around, corrected=False)
    current = next((a for a in original if a.start == start), None)
    if current is None:
        raise ValueError("no_value")
    energy = current.energy_kwh
    limit = sensor.limit_kwh_per_hour * hours(period)
    kind = (
        Kind.SPIKE
        if energy is not None and energy > limit
        else Kind.NEGATIVE
        if energy is not None and energy < NEGATIVE_KWH
        else None
    )
    anomaly = Anomaly(
        entity_id=entity_id,
        device=sensor.device,
        period=period,
        start=start,
        kind=kind or Kind.SPIKE,  # correction d'une valeur plausible : notée comme un saut
        energy_kwh=energy,
        limit_kwh=limit,
    )
    value: float | None = None
    if method is Method.ESTIMATE:
        value = estimate(original, start, period, limit)
        if value is None:
            raise ValueError("no_neighbours")
    elif method is Method.RAW:
        value = recompute(entity_id, period, start) if recompute else None
        if value is None:
            raise ValueError("no_raw")
    return store.add(anomaly, method, value, automatic=False)


# --- Surveillance automatique ----------------------------------------------------------------


class QualityStatus(BaseModel):
    running: bool
    last_run_at: datetime | None = None
    corrected: int = 0  # corrections automatiques depuis le démarrage
    last_error: str | None = None


class Monitor:
    """Analyse les dernières périodes closes toutes les 15 minutes, et la fenêtre de la
    consommation de base au premier passage."""

    def __init__(
        self,
        reader: Reader,
        store: CorrectionStore,
        graph: GraphStore,
        recompute: Recompute | None = None,
    ) -> None:
        self._reader = reader
        self._recompute = recompute
        self._store = store
        self._graph = graph
        self._task: asyncio.Task[None] | None = None
        self._status = QualityStatus(running=False)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        self._status.running = True

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._status.running = False

    def status(self) -> QualityStatus:
        return self._status.model_copy()

    def run(self, now: datetime, first: bool = False) -> Scan:
        home = home_model.load(self._graph)
        saved = configuration_module.load(self._graph)
        periods = {
            HOUR: (now - (FIRST_HOURS if first else RECENT), now),
            QUARTER: (now - (FIRST_QUARTERS if first else RECENT), now),
        }
        found = scan(self._reader, self._store, home, saved, periods, recompute=self._recompute)
        self._status.last_run_at = datetime.now(UTC)
        self._status.corrected += found.corrected
        self._status.last_error = None
        if found.corrected:
            logger.info("Qualité des données : %s périodes écartées", found.corrected)
        return found

    async def _loop(self) -> None:
        first = True
        while True:
            try:
                await asyncio.to_thread(self.run, datetime.now(UTC), first)
                first = False
            except Exception as exc:  # nouvel essai au tour suivant
                self._status.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Analyse de la qualité des données impossible")
            await asyncio.sleep(INTERVAL_S)


# --- Routes ----------------------------------------------------------------------------------

router = APIRouter()


class ScanRequest(BaseModel):
    start: datetime
    end: datetime
    entity_ids: list[str] | None = None  # aucun : tous les compteurs
    periods: list[str] = [HOUR, QUARTER]


class ScanResult(BaseModel):
    anomalies: list[Anomaly]
    corrected: int


class CorrectionRequest(BaseModel):
    entity_id: str
    period: str
    start: datetime
    method: Method


def _recompute(request: Request) -> Recompute | None:
    return getattr(request.app.state.aggregator, "recompute", None)


def _context(request: Request) -> tuple[Reader, CorrectionStore, HomeModel, Configuration]:
    state = request.app.state
    if state.aggregator is None:
        raise HTTPException(status_code=503, detail="not_connected")
    graph = state.graph
    return (
        state.aggregator,
        CorrectionStore(state.database),
        home_model.load(graph),
        configuration_module.load(graph),
    )


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise HTTPException(status_code=422, detail="Heures avec fuseau attendues")
    return moment


@router.post("/api/quality/scan")
def scan_route(request: Request, body: ScanRequest) -> ScanResult:
    """Analyse des compteurs sur une plage ; les cas évidents jamais corrigés sont écartés."""
    start, end = _aware(body.start), _aware(body.end)
    if end <= start or any(p not in PERIODS for p in body.periods):
        raise HTTPException(status_code=422, detail="invalid_range")
    reader, store, home, saved = _context(request)
    found = scan(
        reader,
        store,
        home,
        saved,
        {p: (start, end) for p in body.periods},
        body.entity_ids,
        recompute=_recompute(request),
    )
    return ScanResult(anomalies=found.anomalies, corrected=found.corrected)


@router.get("/api/quality/corrections")
def list_corrections(request: Request, undone: bool = False) -> list[Correction]:
    """Corrections en vigueur (et annulées avec ``undone``), les plus récentes périodes d'abord."""
    return CorrectionStore(request.app.state.database).list(undone)


@router.post("/api/quality/corrections", status_code=201)
def add_correction(request: Request, body: CorrectionRequest) -> Correction:
    """Écarte ou estime une période d'un compteur ; 422 avec un code sinon."""
    if body.period not in PERIODS:
        raise HTTPException(status_code=422, detail="invalid_period")
    reader, store, home, saved = _context(request)
    try:
        return correct(
            reader,
            store,
            home,
            saved,
            body.entity_id,
            body.period,
            _aware(body.start),
            body.method,
            _recompute(request),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/api/quality/corrections/{correction_id}", status_code=204)
def undo_correction(request: Request, correction_id: int) -> Response:
    """Annule une correction : la valeur d'origine revient ; 404 si elle n'est pas en vigueur."""
    if not CorrectionStore(request.app.state.database).undo(correction_id):
        raise HTTPException(status_code=404, detail="unknown_correction")
    return Response(status_code=204)


@router.get("/api/quality/status")
def quality_status(request: Request) -> QualityStatus:
    monitor: Monitor | None = request.app.state.quality
    return monitor.status() if monitor else QualityStatus(running=False)
