"""Besoin d'énergie avant une échéance (lot 3.4).

Véhicule électrique, ballon piloté en puissance (routeur solaire)… : **N kWh à fournir** entre
une heure au plus tôt et une **échéance**, à au plus **P kW**. Le moteur répartit l'énergie
heure par heure, de façon **continue** (charge modulable) ou **par paliers** (tout ou rien à la
puissance maximale). Besoin **quotidien**, ou seulement les jours où une tâche de HA le demande.

Un équipement réglé en besoin d'énergie sans ces réglages reste traité comme un cycle à démarrer.
Lecture du besoin dans HA (SoC d'un véhicule, objectif) : plus tard.
"""

from pydantic import BaseModel, Field
from pyoxigraph import Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, XSD_BOOLEAN, XSD_DOUBLE, vocab
from wattslot.storage.graph import GraphStore

XSD_INTEGER = NamedNode("http://www.w3.org/2001/XMLSchema#integer")


class EnergyNeed(BaseModel):
    energy_kwh: float = Field(gt=0)
    earliest_hour: int = Field(default=0, ge=0, le=23)
    deadline_hour: int = Field(default=24, ge=1, le=24)  # énergie fournie avant cette heure
    max_kw: float = Field(gt=0)
    steps: bool = False  # tout ou rien à la puissance maximale, sinon modulable
    daily: bool = True  # chaque jour, sinon les jours où une tâche de HA le demande


def problems(need: EnergyNeed) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    hours = need.deadline_hour - need.earliest_hour
    if hours <= 0:
        found.append(("need_window_empty", {}))
    elif need.energy_kwh > need.max_kw * hours:
        found.append(("need_too_large", {"hours": str(hours)}))
    return found


def to_triples(owner: NamedNode, need: EnergyNeed) -> list[Triple]:
    node = NamedNode(f"{owner.value}/need")

    def number(value: float) -> Literal:
        return Literal(repr(float(value)), datatype=XSD_DOUBLE)

    def integer(value: int) -> Literal:
        return Literal(str(value), datatype=XSD_INTEGER)

    def boolean(value: bool) -> Literal:
        return Literal(str(value).lower(), datatype=XSD_BOOLEAN)

    return [
        Triple(owner, vocab("hasEnergyNeed"), node),
        Triple(node, RDF_TYPE, vocab("EnergyNeed")),
        Triple(node, vocab("needEnergyKwh"), number(need.energy_kwh)),
        Triple(node, vocab("earliestHour"), integer(need.earliest_hour)),
        Triple(node, vocab("deadlineHour"), integer(need.deadline_hour)),
        Triple(node, vocab("maxKw"), number(need.max_kw)),
        Triple(node, vocab("steps"), boolean(need.steps)),
        Triple(node, vocab("daily"), boolean(need.daily)),
    ]


def load(graph: GraphStore, graph_iri: str, owner: str, vocab_ns: str) -> EnergyNeed | None:
    for row in graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?energy ?earliest ?deadline ?kw ?steps ?daily WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner}> wattslot:hasEnergyNeed ?need .
            ?need wattslot:needEnergyKwh ?energy ; wattslot:earliestHour ?earliest ;
              wattslot:deadlineHour ?deadline ;
              wattslot:maxKw ?kw ; wattslot:steps ?steps ; wattslot:daily ?daily .
          }}
        }}
        """
    ):
        return EnergyNeed(
            energy_kwh=float(row["energy"]),
            earliest_hour=int(row["earliest"]),
            deadline_hour=int(row["deadline"]),
            max_kw=float(row["kw"]),
            steps=row["steps"] == "true",
            daily=row["daily"] == "true",
        )
    return None
