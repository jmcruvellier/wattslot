"""Journal des cycles des équipements, profils de cycle sur 30 jours, cycles réels du jour.

Chaque journée complète est inscrite une fois par équipement à cycles (chauffe-eau, linge,
lave-vaisselle) : cycles détectés sur la puissance et mesurés au compteur (``appliances.py``,
méthode de la v1). Source :

- **brut** (``raw``) quand la journée y est entière : la précision de la v1 ;
- sinon **agrégats au quart d'heure** (``quarters``) : puissance moyenne tenue sur chaque quart
  d'heure, compteur reconstitué par les énergies des quarts d'heure. C'est le cas des journées
  reprises de l'historique de HA ; un cycle y est connu au quart d'heure près.

Le brut n'étant gardé que 3 jours, le journal garde les cycles au-delà : le profil sur 30 jours
devient entièrement précis un mois après la mise en service. Un cycle coupé par minuit (déjà
en marche au début de la journée, ou encore en marche à la fin) est écarté, comme les cycles
coupés par la fenêtre en v1.
"""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from wattslot import configuration as config
from wattslot.aggregation import QUARTER
from wattslot.configuration import Configuration
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, sensor_iri
from wattslot.planning.appliances import (
    PARASITIC_KWH,
    RULES,
    Cycle,
    Observation,
    Profile,
    activity_segments,
    apply_counter,
    measure_cycles,
    profile_from_cycles,
)
from wattslot.planning.cycles import Segment
from wattslot.planning.past import AggregateReader
from wattslot.storage.raw import RawStores

PROFILE_DAYS = 30
CYCLE_KINDS = frozenset(
    {DeviceKind.WATER_HEATER, DeviceKind.WASHING_MACHINE, DeviceKind.DRYER, DeviceKind.DISHWASHER}
)
ALL_KINDS = frozenset(DeviceKind)
QUARTER_STEP = timedelta(minutes=15)


@dataclass(frozen=True)
class Appliance:
    key: str
    name: str
    kind: DeviceKind
    power: tuple[tuple[str, str], ...]  # (entité, IRI du capteur) de puissance
    counter: tuple[tuple[str, str], ...]  # compteurs d'énergie


def _sensors(device: HomeDevice, role: Role) -> tuple[tuple[str, str], ...]:
    return tuple(
        (s.entity_id, sensor_iri(device.key, s.entity_id)) for s in device.sensors if s.role is role
    )


def cycle_appliances(model: HomeModel, configuration: Configuration | None) -> list[Appliance]:
    """Équipements à cycles : ceux que la configuration règle en cycle à démarrer ou en
    besoin d'énergie, quel que soit leur type (lot 3.4) ; sans configuration, comme en phase 2
    (``CYCLE_KINDS``)."""
    if configuration is None:
        return appliances(model)
    keys = config.keys_with(model, configuration, config.CYCLES)
    return [a for a in appliances(model, ALL_KINDS) if a.key in keys]


def appliances(model: HomeModel, kinds: frozenset[DeviceKind] = CYCLE_KINDS) -> list[Appliance]:
    found = []
    for device in model.devices:
        if device.kind not in kinds:
            continue
        power = _sensors(device, Role.POWER_CONSUMED)
        counter = _sensors(device, Role.ENERGY_CONSUMED)
        if power or counter:
            found.append(Appliance(device.key, device.name, device.kind, power, counter))
    return found


def _bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, time(), zone),
        datetime.combine(day + timedelta(days=1), time(), zone),
    )


def _raw_observations(
    raw: RawStores, appliance: Appliance, start: datetime, end: datetime
) -> tuple[list[Observation], list[Observation]]:
    readings = raw.readings(start, end)
    power_iris = {iri for _, iri in appliance.power}
    counter_iris = {iri for _, iri in appliance.counter[:1]}
    power = sorted((t, v) for iri, t, v in readings if iri in power_iris)
    counter = sorted((t, v) for iri, t, v in readings if iri in counter_iris)
    return power, counter


def quarter_observations(
    reader: AggregateReader, appliance: Appliance, start: datetime, end: datetime
) -> tuple[list[Observation], list[Observation]]:
    """Relevés reconstitués depuis les agrégats au quart d'heure : la puissance moyenne tenue
    sur le quart d'heure (ou, sans capteur de puissance, l'énergie du quart d'heure ramenée en
    W), et un compteur cumulé en fin de chaque quart d'heure."""
    energy: dict[datetime, float] = defaultdict(float)
    for entity_id, _ in appliance.counter[:1]:
        for aggregate in reader.read(entity_id, QUARTER, start, end):
            if aggregate.energy_kwh is not None:
                energy[aggregate.start] += aggregate.energy_kwh
    mean: dict[datetime, float] = defaultdict(float)
    for entity_id, _ in appliance.power[:1]:
        for aggregate in reader.read(entity_id, QUARTER, start, end):
            if aggregate.mean is not None:
                mean[aggregate.start] += aggregate.mean
    if not mean:
        mean = {quarter: kwh * 4000 for quarter, kwh in energy.items()}
    power = sorted(mean.items())
    counter: list[Observation] = []
    total = 0.0
    for quarter in sorted(energy):
        if not counter:
            counter.append((quarter, total))
        total += energy[quarter]
        counter.append((quarter + QUARTER_STEP, total))
    return power, counter


def _encode(cycles: Sequence[Cycle]) -> str:
    return json.dumps(
        [
            {
                "start": c.start.isoformat(),
                "end": c.end.isoformat(),
                "energy_kwh": c.energy_kwh,
                "from_counter": c.from_counter,
                "shape": list(c.shape),
            }
            for c in cycles
        ]
    )


def _decode(text: str) -> list[Cycle]:
    return [
        Cycle(
            datetime.fromisoformat(c["start"]),
            datetime.fromisoformat(c["end"]),
            c["energy_kwh"],
            from_counter=c["from_counter"],
            shape=tuple(c["shape"]),
        )
        for c in json.loads(text)
    ]


class CycleJournal:
    def __init__(
        self,
        database: sqlite3.Connection,
        raw: RawStores,
        reader: AggregateReader,
    ) -> None:
        self._database = database
        self._raw = raw
        self._reader = reader

    def _recorded(self, key: str, first: date, last: date) -> dict[date, str]:
        rows = self._database.execute(
            "SELECT day, source FROM appliance_days WHERE device_key = ? AND day BETWEEN ? AND ?",
            (key, first.isoformat(), last.isoformat()),
        )
        return {date.fromisoformat(day): source for day, source in rows}

    def record(self, appliance: Appliance, days: Sequence[date]) -> None:
        """Inscrit les journées absentes du journal (ou connues seulement au quart d'heure alors
        que le brut est là) ; ne touche à aucune autre."""
        if not days:
            return
        zone = self._raw.zone
        raw_days = self._raw.days()
        complete_raw = set(raw_days[1:])  # la première journée du brut est partielle
        known = self._recorded(appliance.key, min(days), max(days))
        missing = [
            d for d in days if d not in known or (known[d] == "quarters" and d in complete_raw)
        ]
        if not missing:
            return
        rows = []
        quarter_days = [d for d in missing if d not in complete_raw]
        if quarter_days:
            start, end = _bounds(min(quarter_days), zone)[0], _bounds(max(quarter_days), zone)[1]
            power, counter = quarter_observations(self._reader, appliance, start, end)
            for day in quarter_days:
                low, high = _bounds(day, zone)
                rows.append((day, "quarters", self._measure(appliance, power, counter, low, high)))
        for day in missing:
            if day in complete_raw:
                low, high = _bounds(day, zone)
                power, counter = _raw_observations(self._raw, appliance, low, high)
                rows.append((day, "raw", self._measure(appliance, power, counter, low, high)))
        with self._database:
            self._database.executemany(
                "INSERT INTO appliance_days VALUES (?, ?, ?, ?) ON CONFLICT(device_key, day) "
                "DO UPDATE SET source = excluded.source, cycles = excluded.cycles",
                [(appliance.key, day.isoformat(), source, _encode(c)) for day, source, c in rows],
            )

    @staticmethod
    def _measure(
        appliance: Appliance,
        power: list[Observation],
        counter: list[Observation],
        low: datetime,
        high: datetime,
    ) -> list[Cycle]:
        day_power = [(t, v) for t, v in power if low <= t < high]
        before = [(t, v) for t, v in power if t < low]
        if before:  # état au début de la journée : le dernier relevé de la veille
            day_power.insert(0, (low, before[-1][1]))
        day_counter = [(t, v) for t, v in counter if t < high + timedelta(hours=1)]
        return measure_cycles(appliance.kind, day_power, day_counter, high, window_start=low)

    def cycles(self, appliance: Appliance, first: date, last: date) -> list[Cycle]:
        rows = self._database.execute(
            "SELECT cycles FROM appliance_days WHERE device_key = ? AND day BETWEEN ? AND ? "
            "ORDER BY day",
            (appliance.key, first.isoformat(), last.isoformat()),
        )
        return [cycle for (text,) in rows for cycle in _decode(text)]

    def profile(self, appliance: Appliance, today: date) -> Profile:
        """Profil de cycle sur les 30 derniers jours complets (journal complété au besoin)."""
        days = [today - timedelta(days=k) for k in range(PROFILE_DAYS, 0, -1)]
        self.record(appliance, days)
        return profile_from_cycles(self.cycles(appliance, days[0], days[-1]))

    def last_cycle_day(self, appliance: Appliance, today: date) -> date | None:
        """Jour (local) du dernier cycle réel avant aujourd'hui, sur les 30 derniers jours."""
        days = [today - timedelta(days=k) for k in range(PROFILE_DAYS, 0, -1)]
        self.record(appliance, days)
        found = self.cycles(appliance, days[0], days[-1])
        zone = self._raw.zone
        return max((c.start.astimezone(zone).date() for c in found), default=None)

    def sources(self, appliance: Appliance, today: date) -> dict[str, int]:
        first = today - timedelta(days=PROFILE_DAYS)
        counts: dict[str, int] = defaultdict(int)
        for source in self._recorded(appliance.key, first, today - timedelta(days=1)).values():
            counts[source] += 1
        return dict(counts)


def real_cycles(
    model: HomeModel, raw: RawStores, now: datetime, configuration: Configuration | None = None
) -> dict[str, tuple[Segment, ...]]:
    """Cycles réels du jour (depuis minuit, heure locale) par équipement, sur le brut : mêmes
    règles que la v1 (``donnees_reelles_du_jour``), compteur relu depuis la veille. Instants en
    heure locale de la maison : le calcul en tire l'heure et la minute du démarrage réel."""
    zone = raw.zone
    midnight = datetime.combine(now.astimezone(zone).date(), time(), zone)
    found: dict[str, tuple[Segment, ...]] = {}
    for appliance in cycle_appliances(model, configuration):
        power, _ = _raw_observations(raw, appliance, midnight, now)
        rules = RULES.get(appliance.kind)
        if rules is None or not power:
            found[appliance.name] = ()
            continue
        cycles = activity_segments(power, now, rules.threshold_w, rules.merge_min, PARASITIC_KWH)
        if cycles and appliance.counter:
            _, counter = _raw_observations(raw, appliance, midnight - timedelta(days=1), now)
            cycles = apply_counter(cycles, counter)
        found[appliance.name] = tuple(
            Segment(c.start.astimezone(zone), c.end.astimezone(zone), c.energy_kwh, c.running)
            for c in cycles
        )
    return found


def profile_summary(profile: Profile) -> dict[str, Any]:
    return {
        "ok": profile.ok,
        "cycles": len(profile.cycles),
        "energy_kwh": profile.energy_kwh,
        "duration_min": profile.duration_min,
        "shape": profile.shape,
    }
