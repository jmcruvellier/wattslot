"""Réglages de la batterie (lot 3.3).

La batterie est facultative : une maison sans batterie dans son modèle n'en a pas au calcul, et
plusieurs batteries sont vues comme une seule (capacités et énergies additionnées). Ce que le
calcul doit en savoir, en plus de ce que HA donne (capacité du modèle, SoC, rendements mesurés) :

- **puissances** de charge et de décharge (W) ; sans réglage : 0,5 C, soit la moitié de la
  capacité par heure ;
- **plancher** de décharge (%), pour la santé de la batterie, et des **plages** où il est plus
  haut (« jamais sous 20 % avant 6 h », lot 3.5) : comme la batterie elle-même est programmée,
  l'application ne la pilotant pas encore ;
- **plage active** : heures où la batterie charge sur le surplus et se décharge sur le déficit
  (autoconsommation) ; hors plage, elle ne fait rien ;
- **charge complète périodique** : au-delà de ce nombre de jours sans charge complète, la
  journée la vise en priorité (étalonnage du BMS) ; ``None`` : jamais.

Valeurs par défaut génériques ; la maison de référence a les siennes (``profiles/reference.json``).
Enregistrés avec la configuration dans le graphe de la maison (décision 12).
"""

from collections.abc import Sequence

from pydantic import BaseModel, Field
from pyoxigraph import BlankNode, Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, XSD_DOUBLE, vocab
from wattslot.storage.graph import GraphStore

XSD_INTEGER = NamedNode("http://www.w3.org/2001/XMLSchema#integer")
C_RATE = 0.5  # puissance par défaut : 0,5 C


def covers(start_hour: int, end_hour: int, hour: int) -> bool:
    """``hour`` est dans ``[start_hour, end_hour)``, à cheval sur minuit si ``start > end``."""
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return start_hour > end_hour and (hour >= start_hour or hour < end_hour)


class FloorRange(BaseModel):
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)  # exclue ; à cheval sur minuit si start_hour > end_hour
    percent: float = Field(ge=0, le=100)


def floor_percent_at(
    floor_percent: float, ranges: Sequence[tuple[int, int, float]], hour: int
) -> float:
    """Plancher (%) à ``hour`` : le plus haut du plancher et des plages qui la couvrent."""
    return max([floor_percent] + [p for start, end, p in ranges if covers(start, end, hour)])


class BatterySettings(BaseModel):
    charge_max_w: float | None = Field(default=None, ge=0)  # None : 0,5 C
    discharge_max_w: float | None = Field(default=None, ge=0)
    floor_percent: float = Field(default=10.0, ge=0, le=100)
    active_from_hour: int = Field(default=0, ge=0, le=23)
    active_to_hour: int = Field(default=24, ge=1, le=24)  # exclue
    full_charge_every_days: int | None = Field(default=7, ge=1)  # None : jamais
    floor_ranges: list[FloorRange] = []  # plancher plus haut sur ces plages (lot 3.5)

    def powers_w(self, capacity_kwh: float) -> tuple[float, float]:
        """(charge, décharge) en W ; 0,5 C sans réglage."""
        default = capacity_kwh * C_RATE * 1000
        return (
            self.charge_max_w if self.charge_max_w is not None else default,
            self.discharge_max_w if self.discharge_max_w is not None else default,
        )


DEFAULT = BatterySettings()


def problems(settings: BatterySettings) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    if settings.active_to_hour <= settings.active_from_hour:
        found.append(("battery_active_range_empty", {}))
    for floor in settings.floor_ranges:
        if floor.start_hour == floor.end_hour:
            found.append(("battery_floor_range_empty", {"range": f"{floor.start_hour}h"}))
    return found


# --- Graphe ----------------------------------------------------------------------------------


def to_triples(owner: NamedNode, settings: BatterySettings) -> list[Triple]:
    node = NamedNode(f"{owner.value}/battery")
    triples = [
        Triple(owner, vocab("hasBatterySettings"), node),
        Triple(node, RDF_TYPE, vocab("BatterySettings")),
        Triple(
            node, vocab("floorPercent"), Literal(repr(settings.floor_percent), datatype=XSD_DOUBLE)
        ),
        Triple(
            node,
            vocab("activeFromHour"),
            Literal(str(settings.active_from_hour), datatype=XSD_INTEGER),
        ),
        Triple(
            node, vocab("activeToHour"), Literal(str(settings.active_to_hour), datatype=XSD_INTEGER)
        ),
    ]
    for name, value in (
        ("chargeMaxW", settings.charge_max_w),
        ("dischargeMaxW", settings.discharge_max_w),
    ):
        if value is not None:
            triples.append(
                Triple(node, vocab(name), Literal(repr(float(value)), datatype=XSD_DOUBLE))
            )
    if settings.full_charge_every_days is not None:
        triples.append(
            Triple(
                node,
                vocab("fullChargeEveryDays"),
                Literal(str(settings.full_charge_every_days), datatype=XSD_INTEGER),
            )
        )
    for index, floor in enumerate(settings.floor_ranges):
        range_node = BlankNode(f"floorrange{index}")
        triples += [
            Triple(node, vocab("hasFloorRange"), range_node),
            Triple(range_node, vocab("order"), Literal(str(index), datatype=XSD_INTEGER)),
            Triple(
                range_node,
                vocab("floorStartHour"),
                Literal(str(floor.start_hour), datatype=XSD_INTEGER),
            ),
            Triple(
                range_node,
                vocab("floorEndHour"),
                Literal(str(floor.end_hour), datatype=XSD_INTEGER),
            ),
            Triple(
                range_node,
                vocab("floorRangePercent"),
                Literal(repr(float(floor.percent)), datatype=XSD_DOUBLE),
            ),
        ]
    return triples


def load(
    graph: GraphStore, graph_iri: str, owner: NamedNode, vocab_ns: str
) -> BatterySettings | None:
    for row in graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?floor ?from ?to ?charge ?discharge ?full WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner.value}> wattslot:hasBatterySettings ?battery .
            ?battery wattslot:floorPercent ?floor ; wattslot:activeFromHour ?from ;
              wattslot:activeToHour ?to .
            OPTIONAL {{ ?battery wattslot:chargeMaxW ?charge }}
            OPTIONAL {{ ?battery wattslot:dischargeMaxW ?discharge }}
            OPTIONAL {{ ?battery wattslot:fullChargeEveryDays ?full }}
          }}
        }}
        """
    ):
        return BatterySettings(
            floor_percent=float(row["floor"]),
            active_from_hour=int(row["from"]),
            active_to_hour=int(row["to"]),
            charge_max_w=float(row["charge"]) if "charge" in row else None,
            discharge_max_w=float(row["discharge"]) if "discharge" in row else None,
            full_charge_every_days=int(row["full"]) if "full" in row else None,
            floor_ranges=_floor_ranges(graph, graph_iri, owner, vocab_ns),
        )
    return None


def _floor_ranges(
    graph: GraphStore, graph_iri: str, owner: NamedNode, vocab_ns: str
) -> list[FloorRange]:
    rows = graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?order ?start ?end ?percent WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner.value}> wattslot:hasBatterySettings ?battery .
            ?battery wattslot:hasFloorRange ?range .
            ?range wattslot:order ?order ; wattslot:floorStartHour ?start ;
              wattslot:floorEndHour ?end ;
              wattslot:floorRangePercent ?percent .
          }}
        }}
        """
    )
    return [
        FloorRange(
            start_hour=int(row["start"]), end_hour=int(row["end"]), percent=float(row["percent"])
        )
        for row in sorted(rows, key=lambda r: int(r["order"]))
    ]
