"""Données réelles du jour (depuis minuit, heure locale), superposées au plan par le dashboard.

Réécriture de ``donnees_reelles_du_jour`` (``forme_horaire_solaire.py``, v1), sur le brut
de l'application au lieu des requêtes SPARQL du MCP ; résultat au format de la v1
(``donnees_reelles_cache``) :

- **SoC** : valeur en fin de chaque heure, moyenne des relevés par heure, maximum instantané et
  SoC à minuit (``_soc_fin_heure``, ``_moyenne_horaire_simple``, ``_soc_max_instantane``,
  ``_soc_minuit``) ;
- **énergies par heure** aux compteurs (``_energie_horaire_compteur``) : production, soutirage,
  injection, charge et décharge de la batterie ; consommation déduite du bilan ;
- **cycles réels** des équipements (``journal.real_cycles``), de la filtration de la piscine
  avec son mode éco ou silence (``_segments_piscine_reelle``) et de la batterie
  (``_segments_batterie_reelle``).

Écart voulu avec la v1 : le modèle de la maison ne connaît pas la puissance signée de la
batterie ; ses segments de charge et de décharge sont tirés de ses compteurs d'énergie (la
puissance tenue entre deux relevés est la hausse du compteur rapportée au temps écoulé). Leur
énergie est donc d'emblée celle des compteurs, comme après ``_ajuster_segments_aux_compteurs``.
La production horaire est aussi lue avec le dernier relevé de la veille, comme les autres
compteurs, là où la v1 partait du premier relevé du jour. Enfin, les baisses des compteurs
suivent la règle des agrégats et non celle de la v1 : à minuit, la v1 repartait de 0 dès que le
premier relevé du jour était plus bas que le dernier de la veille, même d'un millième ; un
compteur total (2048,9 kWh) était alors compté en entier sur la nuit.
"""

import itertools
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from wattslot import configuration as config
from wattslot.aggregation import RESET_RATIO as COUNTER_RESET_RATIO
from wattslot.configuration import Behavior, Configuration
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeModel, sensor_iri
from wattslot.planning.appliances import DEFAULT_RULES, RULES, SHORT_GAP_MIN, Observation
from wattslot.planning.inputs import V1_POOL
from wattslot.planning.journal import appliances, real_cycles
from wattslot.planning.plan import POOL
from wattslot.runtime_settings import MEASURED_SPEED
from wattslot.storage.raw import RawStores

BATTERY_THRESHOLD_W = 30.0  # en deçà, la batterie est au repos (v1 : SEUIL_PUISSANCE_BATTERIE_W)
RESET_RATIO = 0.5  # puissance tirée d'un compteur : une baisse sous la moitié est une remise à zéro


# --- SoC -------------------------------------------------------------------------------------


def _extended(points: Sequence[Observation], until: datetime | None) -> list[Observation]:
    found = sorted(points, key=lambda o: o[0])
    if until is not None and found and until > found[-1][0]:
        found.append((until, found[-1][1]))
    return found


def hourly_mean(
    points: Sequence[Observation], until: datetime | None, zone: ZoneInfo
) -> dict[int, float]:
    """Moyenne des relevés par heure locale (non pondérée), le dernier prolongé à ``until``."""
    values: dict[int, list[float]] = defaultdict(list)
    for moment, value in _extended(points, until):
        values[moment.astimezone(zone).hour].append(value)
    return {hour: sum(v) / len(v) for hour, v in values.items()}


def soc_at_midnight(before: Sequence[Observation], today: Sequence[Observation]) -> float | None:
    """Dernier relevé de la veille, sinon premier du jour."""
    if before:
        return max(before, key=lambda o: o[0])[1]
    if today:
        return min(today, key=lambda o: o[0])[1]
    return None


def soc_end_of_hour(
    points: Sequence[Observation], until: datetime | None, zone: ZoneInfo
) -> dict[int, float]:
    """SoC à la fin de chaque heure locale : dernier relevé connu, tenu d'une heure à l'autre."""
    if not points:
        return {}
    ordered = sorted(points, key=lambda o: o[0])
    last_of_hour = {moment.astimezone(zone).hour: value for moment, value in ordered}
    first = ordered[0][0].astimezone(zone).hour
    last = until.astimezone(zone).hour if until is not None else max(last_of_hour)
    found, current = {}, None
    for hour in range(first, max(last, first) + 1):
        current = last_of_hour.get(hour, current)
        if current is not None:
            found[hour] = current
    return found


def soc_max(points: Sequence[Observation], zone: ZoneInfo) -> dict[str, Any] | None:
    """Maximum instantané et heure locale où il est atteint pour la première fois."""
    if not points:
        return None
    ordered = sorted(points, key=lambda o: o[0])
    best_time, best = ordered[0]
    for moment, value in ordered:
        if value > best:
            best_time, best = moment, value
    return {"pct": best, "heure_iso": best_time.astimezone(zone).isoformat()}


# --- Compteurs d'énergie ---------------------------------------------------------------------


def _spread(start: datetime, end: datetime, delta: float, zone: ZoneInfo) -> dict[int, float]:
    """Hausse répartie au prorata du temps passé dans chaque heure locale."""
    found: dict[int, float] = defaultdict(float)
    start, end = start.astimezone(zone), end.astimezone(zone)
    total = (end - start).total_seconds()
    if total <= 0:
        found[end.hour] += delta
        return dict(found)
    cursor = start
    while cursor < end:
        bound = min(cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1), end)
        found[cursor.hour] += delta * (bound - cursor).total_seconds() / total
        cursor = bound
    return dict(found)


def counter_hourly(
    before: Sequence[Observation],
    today: Sequence[Observation],
    midnight: datetime,
    zone: ZoneInfo,
) -> dict[int, float] | None:
    """kWh par heure locale d'un compteur (total ou remis à zéro à minuit), ``None`` sans
    aucun relevé. Départ : dernier relevé de la veille placé à minuit. Même règle que les
    agrégats (``aggregation.compute``) : une baisse de plus de 10 % est une remise à zéro (la
    nouvelle valeur est comptée), une baisse plus faible du bruit, ignorée sans abaisser la
    base. Chaque hausse est répartie au prorata du temps depuis le relevé précédent."""
    day, previous = sorted(today), sorted(before)
    if not day and not previous:
        return None
    points = list(day)
    if previous:
        points.insert(0, (midnight, previous[-1][1]))
    found: dict[int, float] = defaultdict(float)
    base = points[0][1]
    for (t0, _), (t1, v1) in itertools.pairwise(points):
        if v1 >= base:
            delta = v1 - base
        elif v1 < base * COUNTER_RESET_RATIO:
            delta = v1  # remise à zéro
        else:
            continue  # bruit : la base reste la plus haute valeur vue
        base = v1
        if delta <= 0 or t1 <= t0:
            continue
        for hour, part in _spread(t0, t1, delta, zone).items():
            found[hour] += part
    return dict(found)


def counter_power(points: Sequence[Observation]) -> list[Observation]:
    """Puissance (W) tenue entre deux relevés d'un compteur : la hausse rapportée au temps."""
    ordered = sorted(points, key=lambda o: o[0])
    found: list[Observation] = []
    for (t0, v0), (t1, v1) in itertools.pairwise(ordered):
        delta = v1 - v0
        if delta < 0:
            delta = v1 if v1 < v0 * RESET_RATIO else 0.0
        hours = (t1 - t0).total_seconds() / 3600
        found.append((t0, delta / hours * 1000 if hours > 0 else 0.0))
    if ordered:
        found.append((ordered[-1][0], 0.0))
    return found


# --- Segments réels --------------------------------------------------------------------------


def labelled_segments(
    points: Sequence[Observation],
    until: datetime | None,
    label: Callable[[float], str | None],
    merge_min: float = SHORT_GAP_MIN,
) -> list[tuple[datetime, datetime, str, float]]:
    """Segments d'étiquette constante (chaque relevé tenu jusqu'au suivant) ; coupures courtes
    fusionnées entre deux segments de même étiquette ; énergie signée intégrée par palier (kWh).
    Méthode commune à ``_segments_batterie_reelle`` et ``_segments_piscine_reelle`` (v1)."""
    ordered = _extended(points, until)
    if len(ordered) < 2:
        return []
    raw: list[tuple[datetime, datetime, str]] = []
    start: datetime | None = None
    current: str | None = None
    for (t0, v0), _ in itertools.pairwise(ordered):
        name = label(v0)
        if name != current:
            if current is not None and start is not None:
                raw.append((start, t0, current))
            start, current = (t0, name) if name is not None else (None, None)
    if current is not None and start is not None:
        raw.append((start, ordered[-1][0], current))
    if not raw:
        return []
    merged = [raw[0]]
    for begin, end, name in raw[1:]:
        last_begin, last_end, last_name = merged[-1]
        if name == last_name and (begin - last_end).total_seconds() <= merge_min * 60:
            merged[-1] = (last_begin, end, name)
        else:
            merged.append((begin, end, name))
    found = []
    for begin, end, name in merged:
        energy = 0.0
        for (t0, v0), (t1, _) in itertools.pairwise(ordered):
            low, high = max(t0, begin), min(t1, end)
            if high > low:
                energy += v0 * ((high - low).total_seconds() / 3600) / 1000
        found.append((begin, end, name, energy))
    return found


def battery_segments(
    charged: Sequence[Observation],
    discharged: Sequence[Observation],
    midnight: datetime,
    until: datetime,
    zone: ZoneInfo,
) -> list[dict[str, Any]]:
    """Charges et décharges réelles, tirées des compteurs de la batterie."""
    found = []
    for action, points in (("charge", charged), ("decharge", discharged)):
        power = [(max(t, midnight), w) for t, w in counter_power(points)]

        def label(watts: float, action: str = action) -> str | None:
            return action if watts >= BATTERY_THRESHOLD_W else None

        for begin, end, name, energy in labelled_segments(power, until, label):
            if end > begin:
                found.append((begin, end, name, energy))
    return [
        {
            "debut_iso": begin.astimezone(zone).isoformat(),
            "fin_iso": end.astimezone(zone).isoformat(),
            "action": name,
            "energie_kwh": round(abs(energy), 3),
        }
        for begin, end, name, energy in sorted(found, key=lambda s: s[0])
    ]


def speed_thresholds(speeds: Sequence[tuple[str, float]], on_w: float) -> list[tuple[str, float]]:
    """(mode, puissance minimale en W) de chaque vitesse : la plus basse dès le seuil d'activité,
    les suivantes à mi-chemin de la précédente."""
    ordered = sorted(speeds, key=lambda s: s[1])
    return [
        (name, on_w if index == 0 else (ordered[index - 1][1] + kw) / 2 * 1000)
        for index, (name, kw) in enumerate(ordered)
    ]


def runtime_segments(
    power: Sequence[Observation],
    until: datetime | None,
    zone: ZoneInfo,
    thresholds: Sequence[tuple[str, float]],
) -> list[dict[str, Any]]:
    """Fonctionnement réel d'une durée à placer, le mode déduit de la puissance : la vitesse
    la plus haute dont le seuil est atteint (``speed_thresholds``)."""

    def mode(watts: float) -> str | None:
        return next((name for name, low in reversed(thresholds) if watts >= low), None)

    return [
        {
            "debut_iso": begin.astimezone(zone).isoformat(),
            "fin_iso": end.astimezone(zone).isoformat(),
            "mode": name,
            "energie_kwh": round(energy, 3),
        }
        for begin, end, name, energy in labelled_segments(power, until, mode)
    ]


def pool_segments(
    power: Sequence[Observation],
    until: datetime | None,
    zone: ZoneInfo,
    on_w: float = RULES[DeviceKind.POOL_PUMP].threshold_w,
    eco_w: float | None = None,
) -> list[dict[str, Any]]:
    """Filtration réelle de la v1 (``_segments_piscine_reelle``) : silence, ou éco au-dessus de
    ``eco_w`` (par défaut, à mi-chemin des deux vitesses de la v1)."""
    if eco_w is None:
        return runtime_segments(power, until, zone, speed_thresholds(V1_POOL.speeds, on_w))
    return runtime_segments(power, until, zone, [("silence", on_w), ("eco", eco_w)])


# --- Assemblage ------------------------------------------------------------------------------


def _iris(model: HomeModel, roles: Iterable[Role]) -> dict[Role, list[str]]:
    wanted = set(roles)
    found: dict[Role, list[str]] = defaultdict(list)
    for device in model.devices:
        for sensor in device.sensors:
            if sensor.role in wanted:
                found[sensor.role].append(sensor_iri(device.key, sensor.entity_id))
    return found


def actual_day(
    model: HomeModel,
    raw: RawStores,
    day: date,
    until: datetime,
    manual: bool = False,
    configuration: Configuration | None = None,
) -> dict[str, Any]:
    """Données réelles de ``day`` jusqu'à ``until`` (fin de journée au plus), format de la v1."""
    zone = raw.zone
    midnight = datetime.combine(day, time(), zone)
    until = min(until, midnight + timedelta(days=1))
    readings = raw.readings(midnight - timedelta(days=1), until)
    by_sensor: dict[str, list[Observation]] = defaultdict(list)
    for iri, moment, value in readings:
        by_sensor[iri].append((moment, value))

    def split(iri: str) -> tuple[list[Observation], list[Observation]]:
        points = sorted(by_sensor.get(iri, []))
        return [p for p in points if p[0] < midnight], [p for p in points if p[0] >= midnight]

    iris = _iris(
        model,
        (
            Role.STATE_OF_CHARGE,
            Role.ENERGY_PRODUCED,
            Role.ENERGY_IMPORTED,
            Role.ENERGY_EXPORTED,
            Role.ENERGY_CHARGED,
            Role.ENERGY_DISCHARGED,
        ),
    )

    def hourly(role: Role) -> dict[int, float]:
        total: dict[int, float] = defaultdict(float)
        for iri in iris.get(role, []):
            for hour, kwh in (counter_hourly(*split(iri), midnight, zone) or {}).items():
                total[hour] += kwh
        return dict(total)

    soc_iris = iris.get(Role.STATE_OF_CHARGE, [])
    soc_before, soc_today = split(soc_iris[0]) if soc_iris else ([], [])
    production = hourly(Role.ENERGY_PRODUCED)
    imported, exported = hourly(Role.ENERGY_IMPORTED), hourly(Role.ENERGY_EXPORTED)
    charged, discharged = hourly(Role.ENERGY_CHARGED), hourly(Role.ENERGY_DISCHARGED)
    hours = set(production) | set(imported) | set(exported) | set(charged) | set(discharged)
    consumption = {
        h: production.get(h, 0.0)
        + imported.get(h, 0.0)
        - exported.get(h, 0.0)
        + discharged.get(h, 0.0)
        - charged.get(h, 0.0)
        for h in hours
    }

    def counter(iri: str | None) -> list[Observation]:
        """Relevés du jour d'un compteur, précédés du dernier de la veille."""
        if iri is None:
            return []
        before, today = split(iri)
        return before[-1:] + today

    def first(role: Role) -> str | None:
        return next(iter(iris.get(role, [])), None)

    equipment: dict[str, list[dict[str, Any]]] = {
        name: [
            {
                "debut_iso": s.start.astimezone(zone).isoformat(),
                "fin_iso": s.end.astimezone(zone).isoformat(),
                "energie_kwh": s.energy_kwh,
                **({"en_cours": True} if s.running else {}),
            }
            for s in segments
        ]
        for name, segments in real_cycles(model, raw, until, configuration).items()
    }
    # Durées à placer (filtration…) : celles de la configuration, sinon la piscine de la v1.
    effective = config.effective(model, configuration) if configuration is not None else None
    for runtime in appliances(model, frozenset(DeviceKind)):
        settings = effective.of(runtime.key) if effective is not None else None
        if effective is None and runtime.kind is not DeviceKind.POOL_PUMP:
            continue
        if effective is not None and (
            settings is None or not settings.planned or settings.behavior is not Behavior.RUNTIME
        ):
            continue
        if runtime.power:
            points = split(runtime.power[0][1])[1]
        else:
            power = counter_power(counter(runtime.counter[0][1] if runtime.counter else None))
            points = [(max(t, midnight), w) for t, w in power]
        on_w = RULES.get(runtime.kind, DEFAULT_RULES).threshold_w
        if settings is None:
            equipment[POOL] = pool_segments(points, until, zone, on_w)
            continue
        speeds = [(s.name, s.kw) for s in settings.runtime.speeds] if settings.runtime else []
        thresholds = speed_thresholds(speeds, on_w) if speeds else [(MEASURED_SPEED, on_w)]
        equipment[runtime.name] = runtime_segments(points, until, zone, thresholds)

    return {
        "soc_pct_reel": hourly_mean(soc_today, until, zone),
        "soc_pct_fin_heure": soc_end_of_hour(soc_today, until, zone),
        "soc_max_reel": soc_max(soc_today, zone),
        "soc_pct_minuit": soc_at_midnight(soc_before, soc_today),
        "production_reelle_horaire": production,
        "consommation_reelle_horaire": consumption,
        "reseau_reel_soutire_horaire": imported,
        "reseau_reel_injecte_horaire": exported,
        "equipements_reels_horaire": equipment,
        "batterie_reelle_segments": battery_segments(
            counter(first(Role.ENERGY_CHARGED)),
            counter(first(Role.ENERGY_DISCHARGED)),
            midnight,
            until,
            zone,
        ),
        "heure_maj_iso": until.astimezone(zone).isoformat(),
        "manuel": manual,
    }
