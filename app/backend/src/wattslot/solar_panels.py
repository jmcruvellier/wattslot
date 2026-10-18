"""Panneaux d'une installation solaire (lot 4.4) : ce qu'il faut
pour calculer une prévision Open-Meteo sans intégration de prévision dans HA.

Un ou plusieurs champs (puissance crête, inclinaison, orientation), un onduleur qui plafonne
éventuellement leur somme, et un rendement global (câbles, onduleur, salissures ; l'effet de la
température est calculé à part). L'orientation est en degrés de boussole : 180 plein sud, 90 est,
270 ouest.
"""

from pydantic import BaseModel, Field
from pyoxigraph import Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, XSD_DOUBLE, vocab
from wattslot.storage.graph import GraphStore

XSD_INTEGER = NamedNode("http://www.w3.org/2001/XMLSchema#integer")


class PanelArray(BaseModel):
    kwp: float = Field(gt=0, le=1000)  # puissance crête (kWc)
    tilt: float = Field(default=30, ge=0, le=90)  # inclinaison (°), 0 à plat
    azimuth: float = Field(default=180, ge=0, lt=360)  # orientation (°, boussole)


class SolarPanels(BaseModel):
    arrays: list[PanelArray] = Field(min_length=1)
    inverter_kw: float | None = Field(default=None, gt=0)  # plafond de l'onduleur (kW AC)
    efficiency: float = Field(default=0.9, gt=0, le=1)


def _number(value: float) -> Literal:
    return Literal(repr(float(value)), datatype=XSD_DOUBLE)


def to_triples(owner: NamedNode, panels: SolarPanels) -> list[Triple]:
    node = NamedNode(f"{owner.value}/panels")
    triples = [
        Triple(owner, vocab("hasSolarPanels"), node),
        Triple(node, RDF_TYPE, vocab("SolarPanels")),
        Triple(node, vocab("panelsEfficiency"), _number(panels.efficiency)),
    ]
    if panels.inverter_kw is not None:
        triples.append(Triple(node, vocab("inverterKw"), _number(panels.inverter_kw)))
    for index, array in enumerate(panels.arrays):
        item = NamedNode(f"{node.value}/{index}")
        triples += [
            Triple(node, vocab("hasPanelArray"), item),
            Triple(item, RDF_TYPE, vocab("PanelArray")),
            Triple(item, vocab("arrayIndex"), Literal(str(index), datatype=XSD_INTEGER)),
            Triple(item, vocab("peakPowerKw"), _number(array.kwp)),
            Triple(item, vocab("tiltDegrees"), _number(array.tilt)),
            Triple(item, vocab("azimuthDegrees"), _number(array.azimuth)),
        ]
    return triples


def load(graph: GraphStore, graph_iri: str, owner: str, vocab_ns: str) -> SolarPanels | None:
    found = None
    for row in graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?panels ?efficiency ?inverter WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner}> wattslot:hasSolarPanels ?panels .
            ?panels wattslot:panelsEfficiency ?efficiency .
            OPTIONAL {{ ?panels wattslot:inverterKw ?inverter }}
          }}
        }}
        """
    ):
        found = row
    if found is None:
        return None
    arrays = [
        PanelArray(kwp=float(row["kwp"]), tilt=float(row["tilt"]), azimuth=float(row["azimuth"]))
        for row in graph.select(
            f"""
            PREFIX wattslot: <{vocab_ns}>
            SELECT ?index ?kwp ?tilt ?azimuth WHERE {{
              GRAPH <{graph_iri}> {{
                <{found["panels"]}> wattslot:hasPanelArray ?array .
                ?array wattslot:arrayIndex ?index ; wattslot:peakPowerKw ?kwp ;
                  wattslot:tiltDegrees ?tilt ;
                  wattslot:azimuthDegrees ?azimuth .
              }}
            }}
            ORDER BY ?index
            """
        )
    ]
    if not arrays:
        return None
    return SolarPanels(
        arrays=arrays,
        inverter_kw=float(found["inverter"]) if "inverter" in found else None,
        efficiency=float(found["efficiency"]),
    )
