"""Organisations des données comparées, et leurs requêtes types.

- ``single`` : tout dans le graphe par défaut, au rythme de la v1 (un relevé toutes les
  10 minutes par entité), conservé sur toute la période : la référence de la v1.
- ``partitioned`` : relevés bruts au rythme du temps réel, un graphe nommé par jour, gardés
  quelques jours ; agrégats par quart d'heure (graphe par mois, gardés quelques semaines) et par
  heure (graphe par mois, gardés sans limite).

Chaque requête type reprend un besoin de la v1 (lot 0.5) et renvoie des lignes que
le calcul exploiterait ensuite en Python ; le banc mesure la requête et la lecture des lignes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from bench.data import day_start, iso
from bench.model import APPLIANCES, GRAPH_HOME, SOSA, VOCAB, XSD, Sensor

PREFIXES = f"PREFIX sosa: <{SOSA}>\nPREFIX wattslot: <{VOCAB}>\nPREFIX xsd: <{XSD}>\n"
APPLIANCE_CLASS = f"{VOCAB}class/Appliance"


def raw_graph(day: datetime) -> str:
    return f"{VOCAB}graph:raw:{day:%Y-%m-%d}"


def agg_graph(period: str, month: datetime) -> str:
    return f"{VOCAB}graph:agg:{period}:{month:%Y-%m}"


def months_between(start: datetime, end: datetime) -> list[datetime]:
    months, current = [], start.replace(day=1)
    while current < end:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return months


@dataclass(frozen=True)
class Query:
    name: str
    description: str
    sparql: str


def _sensor(sensors: list[Sensor], role: str, kind: str) -> Sensor:
    return next(s for s in sensors if s.role == role and s.kind == kind)


def single_queries(sensors: list[Sensor], today: int) -> list[Query]:
    end = day_start(today + 1)

    def window(days: int) -> str:
        start = end - timedelta(days=days)
        return f'FILTER(?t >= "{iso(start)}"^^xsd:dateTime && ?t < "{iso(end)}"^^xsd:dateTime)'

    def readings(sensor_iris: list[str], days: int) -> str:
        values = "VALUES ?s { " + " ".join(f"<{i}>" for i in sensor_iris) + " }"
        return (
            f"{PREFIXES}SELECT ?s ?t ?v WHERE {{ {values} "
            f"?o sosa:madeBySensor ?s ; sosa:resultTime ?t ; sosa:hasSimpleResult ?v . "
            f"{window(days)} }} ORDER BY ?s ?t"
        )

    home = _sensor(sensors, "home", "energy").iri
    solar_power = _sensor(sensors, "solar", "power").iri
    appliances = [_sensor(sensors, a, "power").iri for a in APPLIANCES]
    battery = [
        _sensor(sensors, r, "energy").iri for r in ("battery_charge", "battery_discharge", "home")
    ]
    return [
        Query("jour", "Données réelles du jour (production)", readings([solar_power], 1)),
        Query("ligne_base", "Ligne de base, 63 jours (compteur maison)", readings([home], 63)),
        Query("cycles", "Profils de cycle, 30 jours (4 équipements)", readings(appliances, 30)),
        Query("rendements", "Rendements batterie, 30 jours (3 compteurs)", readings(battery, 30)),
        Query(
            "production_max",
            "Meilleure production, 30 jours",
            readings([_sensor(sensors, "solar", "energy").iri], 30),
        ),
        Query(
            "modele",
            "Modèle + observations : équipements, dernière heure",
            f"{PREFIXES}SELECT ?p ?s ?t ?v WHERE {{ "
            f"GRAPH <{GRAPH_HOME}> {{ ?p a <{APPLIANCE_CLASS}> . ?s sosa:isHostedBy ?p }} "
            f"?o sosa:madeBySensor ?s ; sosa:resultTime ?t ; sosa:hasSimpleResult ?v . "
            f'FILTER(?t >= "{iso(end - timedelta(hours=1))}"^^xsd:dateTime) }}',
        ),
    ]


def partitioned_queries(sensors: list[Sensor], today: int) -> list[Query]:
    end = day_start(today + 1)

    def aggregates(sensor_iris: list[str], period: str, days: int, value: str) -> str:
        # Graphes nommés explicitement (UNION) et tri laissé à Python : « VALUES ?g … GRAPH ?g »
        # et ORDER BY rendaient la requête des profils de cycle six fois plus lente (mesure du
        # 14/10/2026).
        start = end - timedelta(days=days)
        pattern = f"?a sosa:madeBySensor ?s ; wattslot:start ?t ; wattslot:{value} ?v"
        graphs = " UNION ".join(
            f"{{ GRAPH <{agg_graph(period, m)}> {{ {pattern} }} }}"
            for m in months_between(start, end)
        )
        sensors_values = "VALUES ?s { " + " ".join(f"<{i}>" for i in sensor_iris) + " }"
        return (
            f"{PREFIXES}SELECT ?s ?t ?v WHERE {{ {sensors_values} {graphs} "
            f'FILTER(?t >= "{iso(start)}"^^xsd:dateTime && ?t < "{iso(end)}"^^xsd:dateTime) }}'
        )

    home = _sensor(sensors, "home", "energy").iri
    solar_power = _sensor(sensors, "solar", "power").iri
    appliances = [_sensor(sensors, a, "power").iri for a in APPLIANCES]
    battery = [
        _sensor(sensors, r, "energy").iri for r in ("battery_charge", "battery_discharge", "home")
    ]
    today_graph = raw_graph(day_start(today))
    last_hour = iso(end - timedelta(hours=1))
    return [
        Query(
            "jour",
            "Données réelles du jour (production)",
            f"{PREFIXES}SELECT ?t ?v WHERE {{ GRAPH <{today_graph}> {{ "
            f"?o sosa:madeBySensor <{solar_power}> ; sosa:resultTime ?t ; "
            f"sosa:hasSimpleResult ?v }} }}",
        ),
        Query(
            "ligne_base",
            "Ligne de base, 63 jours (compteur maison)",
            aggregates([home], "PT1H", 63, "energyKwh"),
        ),
        Query(
            "cycles",
            "Profils de cycle, 30 jours (4 équipements)",
            aggregates(appliances, "PT15M", 30, "mean"),
        ),
        Query(
            "rendements",
            "Rendements batterie, 30 jours (3 compteurs)",
            aggregates(battery, "PT1H", 30, "energyKwh"),
        ),
        Query(
            "production_max",
            "Meilleure production, 30 jours",
            aggregates([_sensor(sensors, "solar", "energy").iri], "PT1H", 30, "energyKwh"),
        ),
        Query(
            "modele",
            "Modèle + observations : équipements, dernière heure",
            f"{PREFIXES}SELECT ?p ?s ?t ?v WHERE {{ "
            f"GRAPH <{GRAPH_HOME}> {{ ?p a <{APPLIANCE_CLASS}> . ?s sosa:isHostedBy ?p }} "
            f"GRAPH <{today_graph}> {{ ?o sosa:madeBySensor ?s ; sosa:resultTime ?t ; "
            f'sosa:hasSimpleResult ?v . FILTER(?t >= "{last_hour}"^^xsd:dateTime) }} }}',
        ),
    ]
