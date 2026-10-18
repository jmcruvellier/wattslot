"""Réglages d'un équipement à durée de fonctionnement à placer (lot 3.4).

Filtration de piscine, déshumidificateur… : chaque heure, l'équipement est à l'arrêt ou tourne à
l'une de ses **vitesses** (puissance connue). Le calcul garantit une **durée minimale par saison**
et peut sauter quelques **jours par saison** (charge complète de la batterie due), avec au plus
un nombre de **démarrages** par jour.

Saisons de l'hémisphère nord : été de juin à septembre, mi-saison en avril, mai et octobre,
hiver de novembre à mars ; décalées de six mois dans l'hémisphère sud (latitude de HA).

Sans vitesse réglée, une seule, dont la puissance est mesurée sur l'historique de l'équipement
(``planning/assemble.py``). Valeurs par défaut des durées : celles de la v1 pour une piscine.
"""

from datetime import date

from pydantic import BaseModel, Field
from pyoxigraph import BlankNode, Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, XSD_DOUBLE, vocab
from wattslot.storage.graph import GraphStore

XSD_INTEGER = NamedNode("http://www.w3.org/2001/XMLSchema#integer")
SEASONS = ("summer", "mid_season", "winter")
MEASURED_SPEED = "normal"  # nom de la vitesse mesurée


def season(day: date, southern: bool = False) -> str:
    month = day.month if not southern else (day.month + 5) % 12 + 1
    if month in (6, 7, 8, 9):
        return "summer"
    if month in (4, 5, 10):
        return "mid_season"
    return "winter"


class Speed(BaseModel):
    name: str  # mode dans le plan (« silence », « eco »…)
    kw: float = Field(gt=0)


class RuntimeSettings(BaseModel):
    speeds: list[Speed] = []  # vide : une vitesse, mesurée sur l'historique
    minimum_hours: dict[str, int] = Field(
        default_factory=lambda: {"summer": 2, "mid_season": 1, "winter": 0}
    )
    skip_days: dict[str, int] = Field(
        default_factory=lambda: {"summer": 1, "mid_season": 2, "winter": 365}
    )
    max_starts: int = Field(default=2, ge=1)


DEFAULT = RuntimeSettings()


def problems(settings: RuntimeSettings) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    names = [s.name for s in settings.speeds]
    if len(names) != len(set(names)) or "off" in names:
        found.append(("runtime_speed_names", {}))
    for mapping in (settings.minimum_hours, settings.skip_days):
        if set(mapping) - set(SEASONS) or any(v < 0 for v in mapping.values()):
            found.append(("runtime_seasons", {}))
            break
    if any(hours > 24 for hours in settings.minimum_hours.values()):
        found.append(("runtime_too_long", {}))
    return found


# --- Graphe ----------------------------------------------------------------------------------


def _integer(value: int) -> Literal:
    return Literal(str(value), datatype=XSD_INTEGER)


def to_triples(owner: NamedNode, settings: RuntimeSettings) -> list[Triple]:
    node = NamedNode(f"{owner.value}/runtime")
    prefix = owner.value.rsplit("/", 1)[-1]
    triples = [
        Triple(owner, vocab("hasRuntimeSettings"), node),
        Triple(node, RDF_TYPE, vocab("RuntimeSettings")),
        Triple(node, vocab("maxStarts"), _integer(settings.max_starts)),
    ]
    for index, speed in enumerate(settings.speeds):
        speed_node = BlankNode(f"{prefix}speed{index}")
        triples += [
            Triple(node, vocab("hasSpeed"), speed_node),
            Triple(speed_node, vocab("order"), _integer(index)),
            Triple(speed_node, vocab("speedName"), Literal(speed.name)),
            Triple(
                speed_node, vocab("powerKw"), Literal(repr(float(speed.kw)), datatype=XSD_DOUBLE)
            ),
        ]
    for prop, mapping in (
        ("minimumHours", settings.minimum_hours),
        ("skipDays", settings.skip_days),
    ):
        for name, value in mapping.items():
            season_node = BlankNode(f"{prefix}{prop}{name}")
            triples += [
                Triple(node, vocab(prop), season_node),
                Triple(season_node, vocab("season"), Literal(name)),
                Triple(season_node, vocab("value"), _integer(value)),
            ]
    return triples


def load(graph: GraphStore, graph_iri: str, owner: str, vocab_ns: str) -> RuntimeSettings | None:
    rows = list(
        graph.select(
            f"""
            PREFIX wattslot: <{vocab_ns}>
            SELECT ?node ?starts WHERE {{
              GRAPH <{graph_iri}> {{
                <{owner}> wattslot:hasRuntimeSettings ?node . ?node wattslot:maxStarts ?starts
              }}
            }}
            """
        )
    )
    if not rows:
        return None
    node = rows[0]["node"]
    speeds = sorted(
        graph.select(
            f"""
            PREFIX wattslot: <{vocab_ns}>
            SELECT ?order ?name ?kw WHERE {{
              GRAPH <{graph_iri}> {{
                <{node}> wattslot:hasSpeed ?speed .
                ?speed wattslot:order ?order ; wattslot:speedName ?name ; wattslot:powerKw ?kw .
              }}
            }}
            """
        ),
        key=lambda row: int(row["order"]),
    )
    mappings: dict[str, dict[str, int]] = {"minimumHours": {}, "skipDays": {}}
    for prop, found in mappings.items():
        for row in graph.select(
            f"""
            PREFIX wattslot: <{vocab_ns}>
            SELECT ?season ?value WHERE {{
              GRAPH <{graph_iri}> {{
                <{node}> wattslot:{prop} ?s . ?s wattslot:season ?season ; wattslot:value ?value
              }}
            }}
            """
        ):
            found[row["season"]] = int(row["value"])
    return RuntimeSettings(
        speeds=[Speed(name=row["name"], kw=float(row["kw"])) for row in speeds],
        minimum_hours=mappings["minimumHours"],
        skip_days=mappings["skipDays"],
        max_starts=int(rows[0]["starts"]),
    )
