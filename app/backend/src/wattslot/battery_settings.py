"""Réglages de la batterie (lot 3.3).

La batterie est facultative : une maison sans batterie dans son modèle n'en a pas au calcul, et
plusieurs batteries sont vues comme une seule (capacités et énergies additionnées). Chaque
batterie peut avoir ses propres réglages, sinon ceux de la maison ; ``combine`` les réunit pour
le calcul. Ce que le calcul doit en savoir, en plus de ce que HA donne (capacité du modèle,
SoC, rendements mesurés) :

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

from wattslot.home_model import RDF_TYPE, XSD_BOOLEAN, XSD_DOUBLE, vocab
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
    # Maison en triphasé : la batterie compense le total des trois phases (elle suit un compteur
    # triphasé) plutôt que sa seule phase. Pas encore lu par le calcul.
    all_phases: bool = False

    def powers_w(self, capacity_kwh: float) -> tuple[float, float]:
        """(charge, décharge) en W ; 0,5 C sans réglage."""
        default = capacity_kwh * C_RATE * 1000
        return (
            self.charge_max_w if self.charge_max_w is not None else default,
            self.discharge_max_w if self.discharge_max_w is not None else default,
        )


DEFAULT = BatterySettings()


def share_of(house: BatterySettings, fraction: float) -> BatterySettings:
    """Réglages de la maison vus par une de ses batteries, qui porte ``fraction`` de la capacité
    totale : les puissances réglées valent pour toutes les batteries ensemble, chacune en prend
    sa part ; le reste (plancher en %, plages, charge complète) vaut tel quel pour chacune."""

    def part(watts: float | None) -> float | None:
        return None if watts is None else watts * fraction

    return house.model_copy(
        update={
            "charge_max_w": part(house.charge_max_w),
            "discharge_max_w": part(house.discharge_max_w),
        }
    )


def _floor_at(settings: BatterySettings, hour: int) -> float:
    ranges = [(r.start_hour, r.end_hour, r.percent) for r in settings.floor_ranges]
    return floor_percent_at(settings.floor_percent, ranges, hour)


def combine(parts: Sequence[tuple[float, BatterySettings]]) -> BatterySettings:
    """Réglages de la batterie unique que voit le calcul, à partir de ceux de chaque batterie
    (capacité en kWh, réglages).

    Exact pour ce qui s'additionne : les puissances, et le plancher en énergie (pourcentages
    pondérés par la capacité, heure par heure). Approché pour le reste : la plage active est
    celle où une batterie au moins fonctionne, la charge complète suit la batterie qui la
    demande le plus souvent."""
    total = sum(capacity for capacity, _ in parts)
    if total <= 0:
        return DEFAULT
    first = parts[0][1]
    if all(settings == first for _, settings in parts):
        return first

    def weighted(hour: int | None) -> float:
        value = sum(
            capacity * (s.floor_percent if hour is None else _floor_at(s, hour))
            for capacity, s in parts
        )
        return round(value / total, 6)

    base = weighted(None)
    ranges: list[FloorRange] = []
    for hour in range(24):
        percent = weighted(hour)
        if percent <= base:
            continue
        last = ranges[-1] if ranges else None
        if last is not None and last.end_hour == hour and last.percent == percent:
            last.end_hour = hour + 1
        else:
            ranges.append(FloorRange(start_hour=hour, end_hour=hour + 1, percent=percent))
    powers = [settings.powers_w(capacity) for capacity, settings in parts]
    every = [s.full_charge_every_days for _, s in parts if s.full_charge_every_days is not None]
    return BatterySettings(
        charge_max_w=sum(charge for charge, _ in powers),
        discharge_max_w=sum(discharge for _, discharge in powers),
        floor_percent=base,
        active_from_hour=min(s.active_from_hour for _, s in parts),
        active_to_hour=max(s.active_to_hour for _, s in parts),
        full_charge_every_days=min(every) if every else None,
        floor_ranges=ranges,
    )


def problems(settings: BatterySettings) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    if settings.active_to_hour <= settings.active_from_hour:
        found.append(("battery_active_range_empty", {}))
    for floor in settings.floor_ranges:
        if floor.start_hour == floor.end_hour:
            found.append(("battery_floor_range_empty", {"range": f"{floor.start_hour}h"}))
    return found


# --- Graphe ----------------------------------------------------------------------------------


def _link(own: bool) -> str:
    """Propriété qui porte les réglages : ceux de la maison, ou ceux propres à une batterie."""
    return "hasOwnBatterySettings" if own else "hasBatterySettings"


def to_triples(owner: NamedNode, settings: BatterySettings, own: bool = False) -> list[Triple]:
    """``own`` : réglages propres à une batterie, ``owner`` étant les réglages de l'équipement."""
    node = NamedNode(f"{owner.value}/battery")
    prefix = f"{owner.value.rsplit('/', 1)[-1]}battery" if own else ""
    triples = [
        Triple(owner, vocab(_link(own)), node),
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
    if settings.all_phases:
        triples.append(Triple(node, vocab("allPhases"), Literal("true", datatype=XSD_BOOLEAN)))
    for index, floor in enumerate(settings.floor_ranges):
        range_node = BlankNode(f"{prefix}floorrange{index}")
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
    graph: GraphStore, graph_iri: str, owner: NamedNode, vocab_ns: str, own: bool = False
) -> BatterySettings | None:
    for row in graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?floor ?from ?to ?charge ?discharge ?full ?all WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner.value}> wattslot:{_link(own)} ?battery .
            ?battery wattslot:floorPercent ?floor ; wattslot:activeFromHour ?from ;
              wattslot:activeToHour ?to .
            OPTIONAL {{ ?battery wattslot:chargeMaxW ?charge }}
            OPTIONAL {{ ?battery wattslot:dischargeMaxW ?discharge }}
            OPTIONAL {{ ?battery wattslot:fullChargeEveryDays ?full }}
            OPTIONAL {{ ?battery wattslot:allPhases ?all }}
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
            floor_ranges=_floor_ranges(graph, graph_iri, owner, vocab_ns, own),
            all_phases=row.get("all") == "true",
        )
    return None


def _floor_ranges(
    graph: GraphStore, graph_iri: str, owner: NamedNode, vocab_ns: str, own: bool
) -> list[FloorRange]:
    rows = graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?order ?start ?end ?percent WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner.value}> wattslot:{_link(own)} ?battery .
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
