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
from wattslot.aggregation import CounterState
from wattslot.configuration import Behavior, Configuration
from wattslot.detection import DeviceKind, Role
from wattslot.home_assistant import is_entity_id
from wattslot.home_model import LINES, HomeDevice, HomeModel, counted_sensors, sensor_iri
from wattslot.planning.appliances import DEFAULT_RULES, RULES, SHORT_GAP_MIN, Observation
from wattslot.planning.inputs import V1_POOL
from wattslot.planning.journal import appliances, real_cycles
from wattslot.planning.past import AggregateReader
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


def combined(
    series: Sequence[Sequence[Observation]], weights: Sequence[float] | None = None
) -> list[Observation]:
    """Relevés de plusieurs capteurs réunis en un seul, à chaque relevé de l'un d'eux. Un capteur
    sans relevé est ignoré ; un seul capteur : ses relevés, triés.

    - Avec ``weights`` (état de charge de plusieurs batteries, pondéré par leur capacité) : la
      moyenne pondérée des dernières valeurs de tous ; rien tant que l'un d'eux n'a pas encore
      de valeur.
    - Sans (compteurs d'énergie) : la somme de ce que chacun a compté depuis son premier relevé.
      Un compteur muet jusque-là ne fait donc ni attendre les autres, ni sauter le total quand
      il parle enfin."""
    kept = [index for index, points in enumerate(series) if points]
    if len(kept) <= 1:
        return sorted(series[kept[0]], key=lambda o: o[0]) if kept else []
    events = sorted(
        ((moment, index, value) for index in kept for moment, value in series[index]),
        key=lambda event: event[0],
    )
    latest: dict[int, float] = {}
    found: list[Observation] = []

    def add(moment: datetime, total: float) -> None:
        if found and found[-1][0] == moment:
            found[-1] = (moment, total)
        else:
            found.append((moment, total))

    if weights is None:
        first: dict[int, float] = {}
        for moment, index, value in events:
            first.setdefault(index, value)
            latest[index] = value
            add(moment, sum(v - first[i] for i, v in latest.items()))
        return found
    known = [weights[index] for index in kept]
    if sum(known) <= 0:
        known = [1.0] * len(kept)
    shares = {index: weight / sum(known) for index, weight in zip(kept, known, strict=True)}
    for moment, index, value in events:
        latest[index] = value
        if len(latest) == len(kept):
            add(moment, sum(shares[i] * v for i, v in latest.items()))
    return found


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
    agrégats (``aggregation.CounterState``) : une baisse de plus de 10 % est une remise à zéro,
    sauf retour à l'index d'avant dans les dix minutes (coupure du capteur), une baisse plus
    faible du bruit, ignorée sans abaisser la base. Chaque hausse est répartie au prorata du
    temps depuis le relevé précédent."""
    day, previous = sorted(today), sorted(before)
    if not day and not previous:
        return None
    points = list(day)
    if previous:
        points.insert(0, (midnight, previous[-1][1]))
    found: dict[int, float] = defaultdict(float)
    state = CounterState(points[0][1], last=points[0][0])
    for (t0, _), (t1, v1) in itertools.pairwise(points):
        # Un relevé ignoré (saut d'index) ne décale pas le début du pas : l'énergie retombe
        # sur l'intervalle depuis le dernier relevé retenu.
        start = state.last_counted or t0
        delta = state.step(t1, v1)
        if delta == 0 or t1 <= start:
            continue
        for hour, part in _spread(start, t1, delta, zone).items():
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
        for sensor in counted_sensors(device):
            if sensor.role in wanted:
                found[sensor.role].append(sensor_iri(device.key, sensor.entity_id))
    return found


def _statistics(model: HomeModel, roles: Iterable[Role]) -> list[tuple[Role, str]]:
    """Statistiques externes (« linky:… ») comptées dans ces rôles : (rôle, identifiant)."""
    wanted = set(roles)
    return [
        (sensor.role, sensor.entity_id)
        for device in model.devices
        for sensor in counted_sensors(device)
        if sensor.role in wanted and not is_entity_id(sensor.entity_id)
    ]


def _statistic_hourly(
    reader: AggregateReader | None,
    entity_id: str,
    midnight: datetime,
    until: datetime,
    zone: ZoneInfo,
) -> dict[int, float]:
    """Énergie par heure locale d'une statistique externe, depuis ses agrégats horaires."""
    if reader is None:
        return {}
    found: dict[int, float] = {}
    for aggregate in reader.read(entity_id, "PT1H", midnight, until):
        if aggregate.energy_kwh is not None:
            hour = aggregate.start.astimezone(zone).hour
            found[hour] = found.get(hour, 0.0) + aggregate.energy_kwh
    return found


def actual_day(
    model: HomeModel,
    raw: RawStores,
    day: date,
    until: datetime,
    manual: bool = False,
    configuration: Configuration | None = None,
    reader: AggregateReader | None = None,
) -> dict[str, Any]:
    """Données réelles de ``day`` jusqu'à ``until`` (fin de journée au plus), format de la v1.

    Statistiques externes (« linky:… ») : pas de brut, leurs heures viennent des agrégats repris
    de HA (``reader``), souvent la veille seulement ; une heure pas encore reçue n'entre pas dans
    la consommation mesurée, au lieu d'y compter pour 0."""
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

    def together(points: list[Observation]) -> tuple[list[Observation], list[Observation]]:
        return [p for p in points if p[0] < midnight], [p for p in points if p[0] >= midnight]

    # Plusieurs batteries : un seul état de charge, pondéré par la capacité de chacune, comme
    # celui d'où part le calcul ; leurs compteurs de charge et de décharge additionnés.
    levels = [
        (device.capacity_kwh or 0.0, by_sensor.get(sensor_iri(device.key, sensor.entity_id), []))
        for device in model.devices
        if device.kind is DeviceKind.BATTERY
        for sensor in device.sensors
        if sensor.role is Role.STATE_OF_CHARGE
    ]
    levels = [(capacity, points) for capacity, points in levels if points] or levels[:1]
    soc_before, soc_today = together(
        combined([points for _, points in levels], [capacity for capacity, _ in levels])
        if levels
        else []
    )
    production = hourly(Role.ENERGY_PRODUCED)
    imported, exported = hourly(Role.ENERGY_IMPORTED), hourly(Role.ENERGY_EXPORTED)
    charged, discharged = hourly(Role.ENERGY_CHARGED), hourly(Role.ENERGY_DISCHARGED)
    flows = {
        Role.ENERGY_PRODUCED: production,
        Role.ENERGY_IMPORTED: imported,
        Role.ENERGY_EXPORTED: exported,
        Role.ENERGY_CHARGED: charged,
        Role.ENERGY_DISCHARGED: discharged,
    }
    received: set[int] | None = None  # heures reçues de toutes les statistiques externes
    for role, entity_id in _statistics(model, flows):
        hours_of = _statistic_hourly(reader, entity_id, midnight, until, zone)
        for hour, kwh in hours_of.items():
            flows[role][hour] = flows[role].get(hour, 0.0) + kwh
        received = set(hours_of) if received is None else received & set(hours_of)
    hours = set(production) | set(imported) | set(exported) | set(charged) | set(discharged)
    if received is not None:
        hours &= received
    # L'onduleur se tait la nuit : les heures mesurées de la maison (réseau, batterie) sans
    # relevé du compteur de production comptent 0 kWh - la courbe mesurée descend au
    # coucher du soleil au lieu de s'arrêter à la fin de la production.
    if iris.get(Role.ENERGY_PRODUCED):
        for h in hours:
            production.setdefault(h, 0.0)
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

    def battery_counter(role: Role) -> list[Observation]:
        """Compteur de toutes les batteries réunies : relevés du jour, précédés du dernier de
        la veille."""
        before, today = together(combined([by_sensor.get(iri, []) for iri in iris.get(role, [])]))
        return before[-1:] + today

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
        for name, segments in real_cycles(model, raw, until, configuration, day).items()
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

    # Capteurs du réseau qui ne mesurent qu'une phase : soutirage et injection de chacune.
    by_phase: dict[str, dict[int, dict[int, float]]] = {}
    series = {
        Role.ENERGY_IMPORTED: "reseau_reel_soutire_par_phase",
        Role.ENERGY_EXPORTED: "reseau_reel_injecte_par_phase",
    }
    for device in model.devices:
        if device.kind is not DeviceKind.GRID:
            continue
        for sensor in device.sensors:
            if sensor.phase not in LINES or sensor.role not in series:
                continue
            measured = counter_hourly(
                *split(sensor_iri(device.key, sensor.entity_id)), midnight, zone
            )
            phase = by_phase.setdefault(series[sensor.role], {}).setdefault(
                LINES.index(sensor.phase) + 1, {}
            )
            for hour, kwh in (measured or {}).items():
                phase[hour] = phase.get(hour, 0.0) + kwh

    # Batteries qui ne compensent que leur phase : charges et décharges réelles de chaque
    # groupe (phase 1 à 3 ; 0 : celles qui compensent le total), pour la frise par phase.
    lines: dict[int, dict[Role, list[list[Observation]]]] = {}
    # Chaque batterie : son groupe et ses propres compteurs, pour la frise par batterie.
    each: list[tuple[HomeDevice, int, dict[Role, list[list[Observation]]]]] = []
    for device in model.devices:
        if device.kind is not DeviceKind.BATTERY:
            continue
        line = config.battery_line(model, configuration, device)
        number = LINES.index(line) + 1 if line is not None else 0
        group = lines.setdefault(number, {})
        own: dict[Role, list[list[Observation]]] = {}
        for sensor in device.sensors:
            if sensor.role in (Role.ENERGY_CHARGED, Role.ENERGY_DISCHARGED):
                points = by_sensor.get(sensor_iri(device.key, sensor.entity_id), [])
                group.setdefault(sensor.role, []).append(points)
                own.setdefault(sensor.role, []).append(points)
        each.append((device, number, own))

    def group_counter(group: dict[Role, list[list[Observation]]], role: Role) -> list[Observation]:
        before, today = together(combined(group.get(role, [])))
        return before[-1:] + today

    battery_lines: dict[str, Any] = {}
    if any(phase for phase in lines):  # au moins une batterie sur une phase
        battery_lines["batterie_reelle_segments_par_phase"] = {
            phase: battery_segments(
                group_counter(group, Role.ENERGY_CHARGED),
                group_counter(group, Role.ENERGY_DISCHARGED),
                midnight,
                until,
                zone,
            )
            for phase, group in sorted(lines.items())
        }

    # Plusieurs batteries : les charges et décharges réelles de chacune (``phase`` : son
    # groupe, comme ci-dessus), montrées sous la ligne de la batterie ou de son groupe. La
    # prévision, elle, n'existe que par groupe : le partage entre batteries d'une même phase
    # dépend de leurs régulateurs.
    if len(each) > 1:
        battery_lines["batterie_reelle_segments_par_batterie"] = [
            {
                "cle": device.key,
                "nom": device.name,
                "phase": number,
                "segments": battery_segments(
                    group_counter(own, Role.ENERGY_CHARGED),
                    group_counter(own, Role.ENERGY_DISCHARGED),
                    midnight,
                    until,
                    zone,
                ),
            }
            for device, number, own in each
        ]

    return {
        **by_phase,
        **battery_lines,
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
            battery_counter(Role.ENERGY_CHARGED),
            battery_counter(Role.ENERGY_DISCHARGED),
            midnight,
            until,
            zone,
        ),
        "heure_maj_iso": until.astimezone(zone).isoformat(),
        "manuel": manual,
    }
