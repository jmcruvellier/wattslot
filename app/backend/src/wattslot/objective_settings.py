"""Objectif du calcul, dans la configuration de la maison (lot 3.6).

Point n° 3 : des **préréglages** (coût, défaut de la décision 13 ; autonomie, soit le moins de
soutirage ; autoconsommation, soit le moins d'injection) et des **poids libres** en réglage
avancé (``custom``). Les poids sont en **équivalent euros** : un kWh soutiré ou injecté y vaut le
prix moyen du jour, si bien qu'un poids dit l'importance d'un critère sans souci d'unités.

Sans objectif dans la configuration, le réglage du calcul (``PlanningSettings.objective``, avant
le lot 3.6) s'applique encore.
"""

from enum import StrEnum

from pydantic import BaseModel, Field
from pyoxigraph import Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, XSD_DOUBLE, vocab
from wattslot.storage.graph import GraphStore


class Preset(StrEnum):
    COST = "cost"
    AUTONOMY = "autonomy"
    SELF_CONSUMPTION = "self_consumption"
    CO2 = "co2"  # avec une entité d'intensité du réseau (``co2_entity``)
    CUSTOM = "custom"


class Weights(BaseModel):
    """Poids de chaque critère (équivalent euros) ; seule leur proportion compte."""

    cost: float = Field(default=1.0, ge=0)  # coût du soutirage moins la revente
    grid_import: float = Field(default=0.0, ge=0)  # kWh soutirés
    grid_export: float = Field(default=0.0, ge=0)  # kWh injectés (autoconsommation)
    # kWh soutirés pondérés par l'intensité carbone de l'heure (moyenne du jour : 1).
    co2: float = Field(default=0.0, ge=0)
    battery: float = Field(default=0.0, ge=0)  # kWh passés par la batterie (ménagement)


class ObjectiveSettings(BaseModel):
    preset: Preset = Preset.COST
    weights: Weights | None = None  # poids libres (``custom``) ; sinon ceux du préréglage
    co2_entity: str | None = None  # intensité carbone du réseau (g/kWh), entité de HA


def problems(settings: ObjectiveSettings) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    weights = settings.weights
    if settings.preset is not Preset.CUSTOM:
        if weights is not None:
            found.append(("objective_weights_unused", {}))
    elif weights is None or sum(weights.model_dump().values()) <= 0:
        found.append(("objective_weights_missing", {}))
    uses_co2 = settings.preset is Preset.CO2 or (
        settings.preset is Preset.CUSTOM and weights is not None and weights.co2 > 0
    )
    if uses_co2 and not settings.co2_entity:
        found.append(("objective_co2_without_entity", {}))
    return found


# --- Graphe ----------------------------------------------------------------------------------

WEIGHT_PROPERTIES = {
    "cost": "costWeight",
    "grid_import": "importWeight",
    "grid_export": "exportWeight",
    "co2": "co2Weight",
    "battery": "batteryWeight",
}


def to_triples(owner: NamedNode, settings: ObjectiveSettings) -> list[Triple]:
    node = NamedNode(f"{owner.value}/objective")
    triples = [
        Triple(owner, vocab("hasObjective"), node),
        Triple(node, RDF_TYPE, vocab("Objective")),
        Triple(node, vocab("objectivePreset"), Literal(settings.preset.value)),
    ]
    if settings.co2_entity:
        triples.append(Triple(node, vocab("co2Entity"), Literal(settings.co2_entity)))
    if settings.weights is not None:
        for name, value in settings.weights.model_dump().items():
            prop = WEIGHT_PROPERTIES[name]
            triples.append(
                Triple(node, vocab(prop), Literal(repr(float(value)), datatype=XSD_DOUBLE))
            )
    return triples


def load(
    graph: GraphStore, graph_iri: str, owner: NamedNode, vocab_ns: str
) -> ObjectiveSettings | None:
    for row in graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?preset ?entity ?cost ?import ?export ?co2 ?battery WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner.value}> wattslot:hasObjective ?node . ?node wattslot:objectivePreset ?preset .
            OPTIONAL {{ ?node wattslot:co2Entity ?entity }}
            OPTIONAL {{ ?node wattslot:costWeight ?cost }}
            OPTIONAL {{ ?node wattslot:importWeight ?import }}
            OPTIONAL {{ ?node wattslot:exportWeight ?export }}
            OPTIONAL {{ ?node wattslot:co2Weight ?co2 }}
            OPTIONAL {{ ?node wattslot:batteryWeight ?battery }}
          }}
        }}
        """
    ):
        variables = {"cost": "cost", "grid_import": "import", "grid_export": "export"}
        variables |= {"co2": "co2", "battery": "battery"}
        weights = (
            Weights(**{name: float(row[v]) for name, v in variables.items() if v in row})
            if "cost" in row
            else None
        )
        return ObjectiveSettings(
            preset=Preset(row["preset"]), weights=weights, co2_entity=row.get("entity")
        )
    return None
