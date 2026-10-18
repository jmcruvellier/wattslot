"""Données synthétiques du banc, en N-Quads.

Deux familles :

- **observations brutes**, au format de la v1 (``sosa:Observation``, 6 triplets chacune), au
  rythme choisi par sorte de capteur ;
- **agrégats** par période (quart d'heure ou heure, 5 triplets chacun) : énergie de la période
  pour un compteur, puissance moyenne et maximale, valeur moyenne pour les autres mesures.

Les valeurs suivent des signaux déterministes simples : le banc mesure des volumes et des durées
de requêtes, pas la justesse des valeurs (les agrégats de puissance sont estimés au milieu de
la période au lieu d'être calculés sur tous les relevés, pour rester rapides à générer).
"""

import math
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from bench.model import RDF_TYPE, SOSA, VOCAB, XSD, Kind, Sensor

START = datetime(2026, 1, 1, tzinfo=UTC)
DAY_S = 86400


def day_start(day: int) -> datetime:
    return START + timedelta(days=day)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def signal(sensor: Sensor, t: datetime) -> float:
    """Valeur d'un capteur à l'instant ``t`` (W, kWh cumulés ou mesure)."""
    seconds = t.timestamp()
    hour = (seconds % DAY_S) / 3600
    if sensor.kind is Kind.ENERGY:
        return (
            sensor.index * 100
            + (0.2 + sensor.index % 5 * 0.1) * (seconds - START.timestamp()) / 3600
        )
    if sensor.kind is Kind.POWER:
        if sensor.role == "solar":
            return max(0.0, math.sin(math.pi * (hour - 7) / 12)) * 2500
        return 150 + 100 * math.sin(seconds / 900 + sensor.index) + 50 * math.sin(seconds / 37)
    return 20 + 5 * math.sin(seconds / 7200 + sensor.index)


def raw_nquads(
    sensors: list[Sensor], day: int, intervals_s: dict[Kind, int], graph: str | None
) -> Iterator[str]:
    """Observations brutes d'une journée, une ligne N-Quads par triplet."""
    g = f" <{graph}>" if graph else ""
    start = day_start(day)
    for sensor in sensors:
        step = intervals_s[sensor.kind]
        prop = sensor.property_iri
        for offset in range(0, DAY_S, step):
            t = start + timedelta(seconds=offset)
            obs = f"<{VOCAB}obs/{sensor.index}/{int(t.timestamp())}>"
            value = signal(sensor, t)
            yield f"{obs} <{RDF_TYPE}> <{SOSA}Observation>{g} .\n"
            yield f"{obs} <{SOSA}madeBySensor> <{sensor.iri}>{g} .\n"
            yield f"{obs} <{SOSA}observedProperty> <{prop}>{g} .\n"
            yield f"{obs} <{SOSA}hasFeatureOfInterest> <{sensor.platform}>{g} .\n"
            yield f'{obs} <{SOSA}resultTime> "{iso(t)}"^^<{XSD}dateTime>{g} .\n'
            yield f'{obs} <{SOSA}hasSimpleResult> "{value:.3f}"^^<{XSD}double>{g} .\n'


def aggregate_nquads(
    sensors: list[Sensor], day: int, period_s: int, graph: Callable[[datetime], str]
) -> Iterator[str]:
    """Agrégats d'une journée pour la période ``period_s`` (900 ou 3600 s)."""
    label = "PT15M" if period_s == 900 else "PT1H"
    start = day_start(day)
    g = f" <{graph(start)}>"
    for sensor in sensors:
        for offset in range(0, DAY_S, period_s):
            t = start + timedelta(seconds=offset)
            agg = f"<{VOCAB}agg/{label}/{sensor.index}/{int(t.timestamp())}>"
            yield f"{agg} <{RDF_TYPE}> <{VOCAB}Aggregate>{g} .\n"
            yield f"{agg} <{SOSA}madeBySensor> <{sensor.iri}>{g} .\n"
            yield f'{agg} <{VOCAB}start> "{iso(t)}"^^<{XSD}dateTime>{g} .\n'
            if sensor.kind is Kind.ENERGY:
                end = t + timedelta(seconds=period_s)
                delta = signal(sensor, end) - signal(sensor, t)
                yield f'{agg} <{VOCAB}energyKwh> "{delta:.4f}"^^<{XSD}double>{g} .\n'
            else:
                mean = signal(sensor, t + timedelta(seconds=period_s / 2))
                yield f'{agg} <{VOCAB}mean> "{mean:.3f}"^^<{XSD}double>{g} .\n'
            if sensor.kind is Kind.POWER:
                yield f'{agg} <{VOCAB}max> "{mean * 1.2:.3f}"^^<{XSD}double>{g} .\n'
            else:
                yield f'{agg} <{VOCAB}period> "{label}"{g} .\n'


def count_lines(lines: Iterator[str]) -> tuple[bytes, int]:
    data = "".join(lines)
    return data.encode(), data.count("\n")
