"""Rejeu de la consommation de base sur l'historique : la méthode actuelle contre trois variantes.

Question posée : l'historique de plus de 9 semaines améliore-t-il la prévision de la
consommation de base (``planning/past.py``) ? Pour chaque journée passée J, le script prévoit J
avec les seules données d'avant J, comme l'application l'aurait fait ce matin-là, puis compare à
ce qui a été mesuré :

- **actuelle** : moyenne des 6 derniers mêmes jours de la semaine (le code de l'application) ;
- **années passées** : ces 6 jours, plus les mêmes jours de la semaine des 3 semaines avant et
  après la même date des années précédentes, tous à poids égal ;
- **tendance** : la méthode actuelle, multipliée par l'évolution constatée l'an dernier à la
  même période (semaines autour de la date, rapportées aux 6 semaines d'avant) ;
- **température** : la méthode actuelle, corrigée par la relation entre consommation du jour et
  température moyenne, apprise sur les 9 dernières semaines (avec ``--latitude`` et
  ``--longitude`` : températures passées d'Open-Meteo ; la température de J est celle mesurée,
  alors que l'application n'aurait eu qu'une prévision : résultat un peu optimiste).

Les données sont lues par l'API de WattSlot (modèle de la maison, réglages, agrégats horaires
corrigés) : rien n'est écrit, ni dans l'application ni sur le disque. Depuis la racine du dépôt,
avec l'environnement Python du serveur :

    python dev/tools/baseline_backtest.py --url http://192.0.2.10:8000
        [--latitude 48.85 --longitude 2.35] [--since 2024-01-01] [--csv rejeu.csv]

Erreur horaire : somme des écarts absolus heure par heure, rapportée à la consommation mesurée.
Erreur du jour : même chose sur le total de la journée. Chaque variante est comparée à la
méthode actuelle sur les mêmes journées (celles où la variante a de quoi prévoir).
"""

import argparse
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from wattslot import configuration as config
from wattslot.aggregation import Aggregate
from wattslot.detection import Role
from wattslot.home_model import HomeModel
from wattslot.planning import past
from wattslot.planning.past import DaySeries

OCCURRENCES = past.SAME_WEEKDAY_OCCURRENCES
WINDOW_DAYS = (OCCURRENCES + past.SAFETY_WEEKS) * 7  # fenêtre de la méthode actuelle
YEAR_DAYS = 364  # 52 semaines : même jour de la semaine
AROUND_WEEKS = 3  # années passées : semaines avant et après la même date
TREND_AFTER = (-1, 0, 1)  # tendance : semaines autour de la date de l'an dernier
MIN_TREND_DAYS = 2
MIN_FIT_DAYS = 14  # température : journées complètes pour apprendre la relation
RATIO_LIMITS = (0.5, 2.0)  # correction bornée : une tendance ou une relation aberrante
CHUNK = timedelta(days=92)  # lecture des agrégats par tranches
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

CURRENT, YEARS, TREND, TEMPERATURE = "actuelle", "années passées", "tendance", "température"
VARIANTS = (YEARS, TREND, TEMPERATURE)

Profile = dict[int, float]  # heure locale → kWh
Fetch = Callable[[str], Any]


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=120) as response:  # adresse donnée par l'appelant
        return json.load(response)


class ApiReader:
    """Agrégats lus par ``/api/aggregates``, par tranches (``past.AggregateReader``)."""

    def __init__(self, url: str, fetch: Fetch = get_json) -> None:
        self._url = url.rstrip("/")
        self._fetch = fetch

    def read(self, entity_id: str, period: str, start: datetime, end: datetime) -> list[Aggregate]:
        found: list[Aggregate] = []
        while start < end:
            stop = min(end, start + CHUNK)
            query = urllib.parse.urlencode(
                {
                    "entity_id": entity_id,
                    "period": period,
                    "start": start.isoformat(),
                    "end": stop.isoformat(),
                }
            )
            rows = self._fetch(f"{self._url}/api/aggregates?{query}")
            found.extend(Aggregate.model_validate(row) for row in rows)
            start = stop
        return found


def load_flows(
    model: HomeModel,
    reader: past.AggregateReader,
    planned: set[str],
    start: datetime,
    end: datetime,
    zone: ZoneInfo,
) -> past._Flows:
    """Flux horaires de toute la période, comme ``past.baseline_detail`` sur sa fenêtre."""

    def read(role: Role) -> DaySeries:
        return past.series(reader, past.sensors(model, [role]), start, end, zone)

    appliances = [
        sensor.entity_id
        for device in model.devices
        if device.key in planned
        for sensor in device.sensors
        if sensor.role is Role.ENERGY_CONSUMED
    ]
    return past._Flows(
        produced=read(Role.ENERGY_PRODUCED),
        imported=read(Role.ENERGY_IMPORTED),
        exported=read(Role.ENERGY_EXPORTED),
        charged=read(Role.ENERGY_CHARGED),
        discharged=read(Role.ENERGY_DISCHARGED),
        appliances=past.series(reader, appliances, start, end, zone),
        has_battery=bool(past.sensors(model, [Role.ENERGY_CHARGED, Role.ENERGY_DISCHARGED])),
    )


def restrict(flows: past._Flows, first: date, end: date) -> past._Flows:
    """Les flux des journées de ``[first, end)`` : ce que l'application voyait le matin de
    ``end``."""

    def cut(found: DaySeries) -> DaySeries:
        return {day: hours for day, hours in found.items() if first <= day < end}

    return replace(
        flows,
        produced=cut(flows.produced),
        imported=cut(flows.imported),
        exported=cut(flows.exported),
        charged=cut(flows.charged),
        discharged=cut(flows.discharged),
        appliances=cut(flows.appliances),
    )


def day_bases(flows: past._Flows) -> dict[date, Profile]:
    """Consommation de base mesurée de chaque journée, par heure : le bilan de
    ``past._typical_detail`` (réseau et batterie présents sur l'heure, équipements planifiés
    retirés)."""
    found: dict[date, Profile] = {}
    for day in set(flows.imported) | set(flows.exported):
        grid = set(flows.imported.get(day, {})) | set(flows.exported.get(day, {}))
        battery = set(flows.charged.get(day, {})) | set(flows.discharged.get(day, {}))
        found[day] = {
            hour: flows.produced.get(day, {}).get(hour, 0.0)
            + flows.imported.get(day, {}).get(hour, 0.0)
            - flows.exported.get(day, {}).get(hour, 0.0)
            + flows.discharged.get(day, {}).get(hour, 0.0)
            - flows.charged.get(day, {}).get(hour, 0.0)
            - flows.appliances.get(day, {}).get(hour, 0.0)
            for hour in (grid & battery if flows.has_battery else grid)
        }
    return found


def total(profile: Profile | None) -> float | None:
    """Total d'une journée complète (24 heures), sinon None."""
    return sum(profile.values()) if profile is not None and len(profile) == 24 else None


def mean_profile(bases: dict[date, Profile], days: Iterable[date]) -> Profile:
    """Moyenne par heure de ces journées, avec les règles de la méthode actuelle : au moins
    ``MIN_DAYS_PER_HOUR`` jours par heure, jamais négative."""
    values: dict[int, list[float]] = {}
    for day in days:
        for hour, kwh in bases.get(day, {}).items():
            values.setdefault(hour, []).append(kwh)
    return {
        hour: max(0.0, sum(found) / len(found))
        for hour, found in sorted(values.items())
        if len(found) >= past.MIN_DAYS_PER_HOUR
    }


def recent_days(bases: dict[date, Profile], target: date) -> list[date] | None:
    """Les 6 derniers mêmes jours de la semaine de la fenêtre ; None s'il y en a moins."""
    first = target - timedelta(days=WINDOW_DAYS)
    same = sorted(
        (d for d in bases if first <= d < target and d.weekday() == target.weekday()),
        reverse=True,
    )
    return same[:OCCURRENCES] if len(same) >= OCCURRENCES else None


def with_past_years(bases: dict[date, Profile], target: date) -> Profile | None:
    """Les 6 jours récents et, pour chaque année passée, les mêmes jours de la semaine des
    ``AROUND_WEEKS`` semaines avant et après la même date."""
    recent = recent_days(bases, target)
    if recent is None:
        return None
    older: list[date] = []
    for year in range(1, 10):
        same_date = target - timedelta(days=YEAR_DAYS * year)
        older.extend(
            day
            for week in range(-AROUND_WEEKS, AROUND_WEEKS + 1)
            if (day := same_date + timedelta(weeks=week)) in bases
        )
    if not older:
        return None
    return mean_profile(bases, [*recent, *older])


def _mean_total(bases: dict[date, Profile], days: Iterable[date], minimum: int) -> float | None:
    totals = [t for day in days if (t := total(bases.get(day))) is not None]
    return sum(totals) / len(totals) if len(totals) >= minimum else None


def _bounded(ratio: float) -> float:
    return min(RATIO_LIMITS[1], max(RATIO_LIMITS[0], ratio))


def scaled(profile: Profile, ratio: float) -> Profile:
    return {hour: kwh * _bounded(ratio) for hour, kwh in profile.items()}


def trend_ratio(bases: dict[date, Profile], target: date) -> float | None:
    """Évolution de l'an dernier à la même période : journées autour de la même date,
    rapportées aux 6 mêmes jours de la semaine d'avant (ceux que la méthode actuelle aurait
    moyennés)."""
    same_date = target - timedelta(days=YEAR_DAYS)
    after = _mean_total(
        bases, (same_date + timedelta(weeks=w) for w in TREND_AFTER), MIN_TREND_DAYS
    )
    before = _mean_total(
        bases,
        (same_date - timedelta(weeks=w) for w in range(1, OCCURRENCES + 1)),
        past.MIN_DAYS_PER_HOUR,
    )
    if after is None or before is None or before <= 0 or after <= 0:
        return None
    return after / before


def temperature_ratio(
    bases: dict[date, Profile], temperatures: dict[date, float], target: date
) -> float | None:
    """Consommation attendue à la température de ``target``, rapportée à celle attendue aux
    températures des 6 jours moyennés : droite ajustée (moindres carrés) sur les journées
    complètes de la fenêtre."""
    recent = recent_days(bases, target)
    if recent is None or target not in temperatures or any(d not in temperatures for d in recent):
        return None
    first = target - timedelta(days=WINDOW_DAYS)
    points = [
        (temperatures[day], t)
        for day, profile in bases.items()
        if first <= day < target and day in temperatures and (t := total(profile)) is not None
    ]
    if len(points) < MIN_FIT_DAYS:
        return None
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread

    def expected(day: date) -> float:
        return mean_y + slope * (temperatures[day] - mean_x)

    reference = sum(expected(day) for day in recent) / len(recent)
    wanted = expected(target)
    if reference <= 0 or wanted <= 0:
        return None
    return wanted / reference


def forecasts(
    flows: past._Flows,
    bases: dict[date, Profile],
    temperatures: dict[date, float],
    target: date,
) -> dict[str, Profile]:
    """Prévisions de ``target`` par chaque méthode qui a de quoi prévoir, avec les seules
    données d'avant ``target`` (la tendance lit l'an dernier, donc aussi avant)."""
    window = restrict(flows, target - timedelta(days=WINDOW_DAYS), target)
    current = past._typical_detail(window, target, OCCURRENCES).kwh
    if not current:
        return {}
    found = {CURRENT: current}
    if (years := with_past_years(bases, target)) is not None:
        found[YEARS] = years
    if (ratio := trend_ratio(bases, target)) is not None:
        found[TREND] = scaled(current, ratio)
    if (ratio := temperature_ratio(bases, temperatures, target)) is not None:
        found[TEMPERATURE] = scaled(current, ratio)
    return found


@dataclass
class Score:
    """Écarts cumulés d'une variante et de la méthode actuelle, sur les mêmes journées."""

    days: int = 0
    measured: float = 0.0
    hourly: float = 0.0
    hourly_current: float = 0.0
    daily: float = 0.0
    daily_current: float = 0.0
    bias: float = 0.0
    better: int = 0

    def add(self, measured: Profile, current: Profile, variant: Profile) -> None:
        hours = range(24)
        error = sum(abs(variant[h] - measured[h]) for h in hours)
        error_current = sum(abs(current[h] - measured[h]) for h in hours)
        sums = [sum(p[h] for h in hours) for p in (measured, current, variant)]
        self.days += 1
        self.measured += sums[0]
        self.hourly += error
        self.hourly_current += error_current
        self.daily += abs(sums[2] - sums[0])
        self.daily_current += abs(sums[1] - sums[0])
        self.bias += sums[2] - sums[0]
        self.better += error < error_current

    def percent(self, value: float) -> float:
        return 100 * value / self.measured if self.measured else 0.0


@dataclass
class Result:
    first: date | None = None
    last: date | None = None
    days: int = 0
    overall: dict[str, Score] = field(default_factory=dict)
    monthly: dict[str, dict[str, Score]] = field(default_factory=dict)  # variante → mois
    rows: list[dict[str, Any]] = field(default_factory=list)  # une ligne par journée (--csv)


def replay(
    flows: past._Flows, temperatures: dict[date, float] | None = None, since: date | None = None
) -> Result:
    """Rejoue chaque journée complète mesurée, à partir de ``since``."""
    bases = day_bases(flows)
    result = Result()
    for target in sorted(bases):
        measured = bases[target]
        if (since is not None and target < since) or len(measured) != 24:
            continue
        found = forecasts(flows, bases, temperatures or {}, target)
        current = found.get(CURRENT)
        if current is None or len(current) != 24:
            continue
        result.first = result.first or target
        result.last = target
        result.days += 1
        row: dict[str, Any] = {
            "jour": target.isoformat(),
            "mesuré": round(sum(measured.values()), 3),
        }
        row[CURRENT] = round(sum(current.values()), 3)
        for name in VARIANTS:
            variant = found.get(name)
            if variant is None or len(variant) != 24:
                continue
            row[name] = round(sum(variant.values()), 3)
            for score in (
                result.overall.setdefault(name, Score()),
                result.monthly.setdefault(name, {}).setdefault(f"{target:%Y-%m}", Score()),
            ):
                score.add(measured, current, variant)
        result.rows.append(row)
    return result


def _line(label: str, score: Score) -> str:
    gain = score.percent(score.hourly_current) - score.percent(score.hourly)
    return (
        f"{label:<16}{score.days:>6}"
        f"{score.percent(score.hourly):>10.1f} %{score.percent(score.hourly_current):>10.1f} %"
        f"{gain:>+9.1f}"
        f"{score.percent(score.daily):>10.1f} %{score.percent(score.daily_current):>10.1f} %"
        f"{score.percent(score.bias):>+9.1f} %"
        f"{100 * score.better / score.days if score.days else 0:>9.0f} %"
    )


HEADER = (
    f"{'':<16}{'jours':>6}{'horaire':>12}{'actuelle':>12}{'gain':>9}"
    f"{'du jour':>12}{'actuelle':>12}{'biais':>11}{'meilleure':>11}"
)


def report(result: Result) -> str:
    if not result.days:
        return "Aucune journée à rejouer : pas assez d'historique horaire."
    lines = [
        f"Journées rejouées : {result.days}, du {result.first} au {result.last}.",
        "Erreurs en % de la consommation mesurée ; « actuelle » : la méthode actuelle sur les",
        "mêmes journées ; gain : points d'erreur horaire en moins (positif : la variante fait",
        "mieux) ; meilleure : part des journées où la variante se trompe moins.",
        "",
        HEADER,
    ]
    for name in VARIANTS:
        if name in result.overall:
            lines.append(_line(name, result.overall[name]))
        else:
            lines.append(f"{name:<16}{'-':>6}   (pas de données pour cette variante)")
    for name in VARIANTS:
        if name not in result.monthly:
            continue
        lines += ["", f"Par mois, {name} :", HEADER]
        lines += [_line(month, score) for month, score in sorted(result.monthly[name].items())]
    return "\n".join(lines)


def temperatures_from(payload: Any) -> dict[date, float]:
    daily = payload.get("daily", {})
    return {
        date.fromisoformat(day): float(value)
        for day, value in zip(
            daily.get("time", []), daily.get("temperature_2m_mean", []), strict=False
        )
        if value is not None
    }


def load_temperatures(
    latitude: float,
    longitude: float,
    first: date,
    last: date,
    time_zone: str,
    fetch: Fetch = get_json,
) -> dict[date, float]:
    """Températures moyennes journalières passées (Open-Meteo) ; coordonnées arrondies comme
    dans l'application (``planning/open_meteo.py``)."""
    query = urllib.parse.urlencode(
        {
            "latitude": f"{latitude:.2f}",
            "longitude": f"{longitude:.2f}",
            "start_date": first.isoformat(),
            "end_date": last.isoformat(),
            "daily": "temperature_2m_mean",
            "timezone": time_zone,
        }
    )
    return temperatures_from(fetch(f"{ARCHIVE_URL}?{query}"))


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", required=True, help="adresse de WattSlot (http://hôte:port)")
    parser.add_argument("--since", type=date.fromisoformat, help="première journée lue")
    parser.add_argument("--years", type=int, default=3, help="années lues sans --since")
    parser.add_argument("--time-zone", help="fuseau de la maison (sinon celui de l'application)")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--csv", type=Path, help="détail par journée (totaux en kWh)")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    time_zone = args.time_zone or get_json(f"{url}/api/health").get("time_zone")
    if not time_zone:
        print("Fuseau horaire inconnu : le donner avec --time-zone.", file=sys.stderr)
        return 2
    zone = ZoneInfo(time_zone)
    model = HomeModel.model_validate(get_json(f"{url}/api/home"))
    settings = config.Configuration.model_validate(get_json(f"{url}/api/configuration"))
    planned = config.keys_with(model, settings, config.SCHEDULED)
    today = datetime.now(zone).date()
    first = args.since or today - timedelta(days=365 * args.years)
    print(f"Lecture des agrégats horaires depuis le {first}…", file=sys.stderr)
    flows = load_flows(
        model,
        ApiReader(url),
        planned,
        datetime.combine(first, time(), zone),
        datetime.combine(today, time(), zone),
        zone,
    )
    temperatures: dict[date, float] = {}
    if args.latitude is not None and args.longitude is not None:
        days = set(flows.imported) | set(flows.exported)
        if days:
            temperatures = load_temperatures(
                args.latitude, args.longitude, min(days), max(days), time_zone
            )
    else:
        print("Sans --latitude et --longitude : variante « température » ignorée.", file=sys.stderr)
    result = replay(flows, temperatures)
    print(report(result))
    if args.csv is not None and result.rows:
        with args.csv.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, ["jour", "mesuré", CURRENT, *VARIANTS])
            writer.writeheader()
            writer.writerows(result.rows)
        print(f"Détail par journée : {args.csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as exc:
        print(f"Lecture impossible ({exc}) : vérifier l'adresse donnée à --url.", file=sys.stderr)
        sys.exit(2)
