"""Contexte tarifaire générique (décision 10, lot 3.2).

Un tarif donne le prix du kWh soutiré à chaque heure d'une journée, et celui du kWh injecté :

- **prix unique** (``SingleTariff``) : ``base_eur_kwh`` à toute heure ;
- **plages horaires** (``TimeOfUseTariff``) : des plages ``[début, fin[`` en heures locales, chacune
  avec son prix, limitées au besoin à certains jours de la semaine ou à certains mois (heures
  creuses et pleines, saisons, week-ends) ; une heure hors de toute plage est au prix de base ;
  si plusieurs plages couvrent une heure, la première l'emporte ;
- **couleur du jour** (``DayColorTariff``, Tempo) : un prix de base et des plages par couleur ; la
  couleur du jour et celle du lendemain sont lues dans des entités HA, la première couleur
  déclarée servant au-delà. Un jour de couleur peut commencer à une autre heure que minuit
  (6 h pour Tempo : de 0 h à 6 h, c'est la couleur de la veille) ;
- **prix dynamique** (``DynamicTariff``) : prix lus dans les attributs d'une entité HA (prévision
  heure par heure ou au quart d'heure, moyennée par heure) ; une heure sans prix connu prend le
  prix de base.

Le prix de revente est fixe, ou lu de la même façon dans une entité. Ce qui vient de HA
(couleurs, prix connus) forme un ``TariffContext``, lu une fois par calcul
(``planning/sources.tariff_context``).

Sans tarif configuré, ``DEFAULT`` : un prix unique, qui revient à soutirer le moins possible.
Enregistré avec la configuration dans le graphe de la maison (décision 12).
"""

import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field
from pyoxigraph import BlankNode, Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, XSD_DOUBLE, vocab
from wattslot.storage.graph import GraphStore

XSD_INTEGER = NamedNode("http://www.w3.org/2001/XMLSchema#integer")


class TariffKind(StrEnum):
    SINGLE = "SingleTariff"
    TIME_OF_USE = "TimeOfUseTariff"
    DAY_COLOR = "DayColorTariff"
    DYNAMIC = "DynamicTariff"


class PriceBand(BaseModel):
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)  # exclue
    eur_kwh: float = Field(ge=0)
    weekdays: list[int] = []  # 0 lundi … 6 dimanche ; vide : tous les jours
    months: list[int] = []  # 1 … 12 ; vide : toute l'année

    def applies(self, day: date, hour: int) -> bool:
        return (
            self.start_hour <= hour < self.end_hour
            and (not self.weekdays or day.weekday() in self.weekdays)
            and (not self.months or day.month in self.months)
        )


class ColorPrices(BaseModel):
    color: str  # état de l'entité de couleur (casse, accents et anglais ignorés)
    base_eur_kwh: float = Field(ge=0)
    bands: list[PriceBand] = []


def _price(bands: list[PriceBand], base: float, day: date, hour: int) -> float:
    return next((band.eur_kwh for band in bands if band.applies(day, hour)), base)


# Couleurs reconnues dans les deux langues (intégrations Tempo de HA).
SYNONYMS = {"blue": "bleu", "white": "blanc", "red": "rouge"}


def color_key(text: str) -> str:
    plain = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    key = plain.strip().casefold()
    return SYNONYMS.get(key, key)


@dataclass
class TariffContext:
    """Ce que HA apprend du tarif pour un calcul : couleurs des jours, prix connus par heure."""

    colors: dict[date, str] = field(default_factory=dict)
    prices: dict[date, dict[int, float]] = field(default_factory=dict)
    export: dict[date, dict[int, float]] = field(default_factory=dict)


NO_CONTEXT = TariffContext()


class Tariff(BaseModel):
    kind: TariffKind = TariffKind.SINGLE
    base_eur_kwh: float = Field(ge=0)  # prix unique, hors de toute plage, ou prix inconnu
    bands: list[PriceBand] = []  # plages horaires (TimeOfUseTariff)
    export_eur_kwh: float = Field(default=0.0, ge=0)  # revente du surplus (ou prix inconnu)
    # Couleur du jour (DayColorTariff)
    colors: list[ColorPrices] = []  # la première : couleur d'un jour inconnu
    color_entity: str | None = None
    color_tomorrow_entity: str | None = None
    color_day_start_hour: int = Field(default=0, ge=0, le=23)
    # Prix dynamique (DynamicTariff) et revente lue dans HA
    price_entity: str | None = None
    export_entity: str | None = None
    price_factor: float = Field(default=1.0, gt=0)  # unité des entités → €/kWh (0,001 : €/MWh)

    def _color_prices(self, day: date, context: TariffContext) -> ColorPrices | None:
        known = context.colors.get(day)
        found = next(
            (c for c in self.colors if known and color_key(c.color) == color_key(known)), None
        )
        return found or (self.colors[0] if self.colors else None)

    def hourly(self, day: date, context: TariffContext = NO_CONTEXT) -> dict[int, float]:
        """Prix du kWh soutiré à chaque heure locale de ``day``."""
        if self.kind is TariffKind.TIME_OF_USE:
            return {h: _price(self.bands, self.base_eur_kwh, day, h) for h in range(24)}
        if self.kind is TariffKind.DAY_COLOR:
            found: dict[int, float] = {}
            for hour in range(24):
                color_day = day if hour >= self.color_day_start_hour else day - timedelta(days=1)
                prices = self._color_prices(color_day, context)
                found[hour] = (
                    _price(prices.bands, prices.base_eur_kwh, day, hour)
                    if prices
                    else self.base_eur_kwh
                )
            return found
        if self.kind is TariffKind.DYNAMIC:
            known = context.prices.get(day, {})
            return {h: known.get(h, self.base_eur_kwh) for h in range(24)}
        return dict.fromkeys(range(24), self.base_eur_kwh)

    def export_hourly(self, day: date, context: TariffContext = NO_CONTEXT) -> dict[int, float]:
        """Prix du kWh injecté à chaque heure locale de ``day``."""
        known = context.export.get(day, {})
        return {h: known.get(h, self.export_eur_kwh) for h in range(24)}


def off_peak_ranges(
    tariff: Tariff, day: date, context: TariffContext = NO_CONTEXT
) -> list[tuple[int, int]]:
    """Plages ``[début, fin[`` des heures moins chères que l'heure la plus chère de ``day``
    (heures creuses du dashboard) ; aucune pour un prix unique."""
    prices = tariff.hourly(day, context)
    top = max(prices.values())
    ranges: list[tuple[int, int]] = []
    for hour in range(24):
        if prices[hour] < top:
            if ranges and ranges[-1][1] == hour:
                ranges[-1] = (ranges[-1][0], hour + 1)
            else:
                ranges.append((hour, hour + 1))
    return ranges


# Sans tarif configuré : un prix unique, ordre de grandeur des tarifs de détail européens.
DEFAULT = Tariff(kind=TariffKind.SINGLE, base_eur_kwh=0.25)
# Tarif implicite de la v1 (heures creuses de 0 h à 6 h et de 22 h à 24 h, prix indicatifs) :
# celui d'une entrée au format de la v1 (``inputs.from_v1``, les 13 états capturés).
V1 = Tariff(
    kind=TariffKind.TIME_OF_USE,
    base_eur_kwh=0.27,
    bands=[
        PriceBand(start_hour=0, end_hour=6, eur_kwh=0.21),
        PriceBand(start_hour=22, end_hour=24, eur_kwh=0.21),
    ],
)


def _band_problems(bands: list[PriceBand], prefix: str) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    for index, band in enumerate(bands):
        params = {"band": f"{prefix}{index + 1}"}
        if band.end_hour <= band.start_hour:
            found.append(("band_empty", params))
        if any(not 0 <= d <= 6 for d in band.weekdays):
            found.append(("band_weekday", params))
        if any(not 1 <= m <= 12 for m in band.months):
            found.append(("band_month", params))
    return found


def problems(tariff: Tariff) -> list[tuple[str, dict[str, str]]]:
    """Anomalies (code, paramètres) d'un tarif."""
    found: list[tuple[str, dict[str, str]]] = []
    if tariff.kind is TariffKind.TIME_OF_USE and not tariff.bands:
        found.append(("tariff_without_bands", {}))
    if tariff.kind is not TariffKind.TIME_OF_USE and tariff.bands:
        found.append(("bands_not_used", {}))
    if tariff.kind is TariffKind.DAY_COLOR:
        if not tariff.colors:
            found.append(("tariff_without_colors", {}))
        if not tariff.color_entity:
            found.append(("tariff_without_color_entity", {}))
        keys = [color_key(c.color) for c in tariff.colors]
        if len(keys) != len(set(keys)):
            found.append(("color_twice", {}))
    if tariff.kind is TariffKind.DYNAMIC and not tariff.price_entity:
        found.append(("tariff_without_price_entity", {}))
    found += _band_problems(tariff.bands, "")
    for color in tariff.colors:
        found += _band_problems(color.bands, f"{color.color} ")
    return found


# --- Graphe ----------------------------------------------------------------------------------


def _number(value: float) -> Literal:
    return Literal(repr(float(value)), datatype=XSD_DOUBLE)


def _integer(value: int) -> Literal:
    return Literal(str(value), datatype=XSD_INTEGER)


def _bands_triples(owner: NamedNode, bands: list[PriceBand], prefix: str) -> list[Triple]:
    triples: list[Triple] = []
    for index, band in enumerate(bands):
        node = BlankNode(f"{prefix}band{index}")
        triples += [
            Triple(owner, vocab("hasPriceBand"), node),
            Triple(node, RDF_TYPE, vocab("PriceBand")),
            Triple(node, vocab("order"), _integer(index)),
            Triple(node, vocab("startHour"), _integer(band.start_hour)),
            Triple(node, vocab("endHour"), _integer(band.end_hour)),
            Triple(node, vocab("priceEurKwh"), _number(band.eur_kwh)),
        ]
        triples += [Triple(node, vocab("weekday"), _integer(d)) for d in band.weekdays]
        triples += [Triple(node, vocab("month"), _integer(m)) for m in band.months]
    return triples


def to_triples(owner: NamedNode, tariff: Tariff) -> list[Triple]:
    node = NamedNode(f"{owner.value}/tariff")
    triples = [
        Triple(owner, vocab("hasTariff"), node),
        Triple(node, RDF_TYPE, vocab(tariff.kind)),
        Triple(node, vocab("basePriceEurKwh"), _number(tariff.base_eur_kwh)),
        Triple(node, vocab("exportPriceEurKwh"), _number(tariff.export_eur_kwh)),
        Triple(node, vocab("colorDayStartHour"), _integer(tariff.color_day_start_hour)),
        Triple(node, vocab("priceFactor"), _number(tariff.price_factor)),
    ]
    for name, value in (
        ("colorEntity", tariff.color_entity),
        ("colorTomorrowEntity", tariff.color_tomorrow_entity),
        ("priceEntity", tariff.price_entity),
        ("exportPriceEntity", tariff.export_entity),
    ):
        if value:
            triples.append(Triple(node, vocab(name), Literal(value)))
    triples += _bands_triples(node, tariff.bands, "")
    for index, color in enumerate(tariff.colors):
        color_node = NamedNode(f"{node.value}/color/{index}")
        triples += [
            Triple(node, vocab("hasColorPrices"), color_node),
            Triple(color_node, RDF_TYPE, vocab("ColorPrices")),
            Triple(color_node, vocab("order"), _integer(index)),
            Triple(color_node, vocab("color"), Literal(color.color)),
            Triple(color_node, vocab("basePriceEurKwh"), _number(color.base_eur_kwh)),
        ]
        triples += _bands_triples(color_node, color.bands, f"color{index}")
    return triples


def _load_bands(graph: GraphStore, graph_iri: str, owner: str, vocab_ns: str) -> list[PriceBand]:
    bands: dict[int, PriceBand] = {}
    for row in graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?order ?start ?end ?price ?weekday ?month WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner}> wattslot:hasPriceBand ?band .
            ?band wattslot:order ?order ; wattslot:startHour ?start ; wattslot:endHour ?end ;
              wattslot:priceEurKwh ?price .
            OPTIONAL {{ ?band wattslot:weekday ?weekday }}
            OPTIONAL {{ ?band wattslot:month ?month }}
          }}
        }}
        """
    ):
        band = bands.setdefault(
            int(row["order"]),
            PriceBand(
                start_hour=int(row["start"]),
                end_hour=int(row["end"]),
                eur_kwh=float(row["price"]),
            ),
        )
        if "weekday" in row and int(row["weekday"]) not in band.weekdays:
            band.weekdays.append(int(row["weekday"]))
        if "month" in row and int(row["month"]) not in band.months:
            band.months.append(int(row["month"]))
    for band in bands.values():
        band.weekdays.sort()
        band.months.sort()
    return [bands[k] for k in sorted(bands)]


def load(graph: GraphStore, graph_iri: str, owner: NamedNode, vocab_ns: str) -> Tariff | None:
    rows = list(
        graph.select(
            f"""
            PREFIX wattslot: <{vocab_ns}>
            SELECT ?tariff ?kind ?base ?export ?start ?factor ?colorEntity ?tomorrow ?price
                   ?exportEntity WHERE {{
              GRAPH <{graph_iri}> {{
                <{owner.value}> wattslot:hasTariff ?tariff .
                ?tariff a ?kind ; wattslot:basePriceEurKwh ?base ;
                  wattslot:exportPriceEurKwh ?export .
                OPTIONAL {{ ?tariff wattslot:colorDayStartHour ?start }}
                OPTIONAL {{ ?tariff wattslot:priceFactor ?factor }}
                OPTIONAL {{ ?tariff wattslot:colorEntity ?colorEntity }}
                OPTIONAL {{ ?tariff wattslot:colorTomorrowEntity ?tomorrow }}
                OPTIONAL {{ ?tariff wattslot:priceEntity ?price }}
                OPTIONAL {{ ?tariff wattslot:exportPriceEntity ?exportEntity }}
              }}
            }}
            """
        )
    )
    if not rows:
        return None
    row = rows[0]
    node = row["tariff"]
    colors = [
        ColorPrices(
            color=color["color"],
            base_eur_kwh=float(color["base"]),
            bands=_load_bands(graph, graph_iri, color["node"], vocab_ns),
        )
        for color in sorted(
            graph.select(
                f"""
                PREFIX wattslot: <{vocab_ns}>
                SELECT ?node ?order ?color ?base WHERE {{
                  GRAPH <{graph_iri}> {{
                    <{node}> wattslot:hasColorPrices ?node .
                    ?node wattslot:order ?order ; wattslot:color ?color ;
                      wattslot:basePriceEurKwh ?base .
                  }}
                }}
                """
            ),
            key=lambda c: int(c["order"]),
        )
    ]
    return Tariff(
        kind=TariffKind(row["kind"].removeprefix(vocab_ns)),
        base_eur_kwh=float(row["base"]),
        export_eur_kwh=float(row["export"]),
        bands=_load_bands(graph, graph_iri, node, vocab_ns),
        colors=colors,
        color_entity=row.get("colorEntity"),
        color_tomorrow_entity=row.get("tomorrow"),
        color_day_start_hour=int(row.get("start", 0)),
        price_entity=row.get("price"),
        export_entity=row.get("exportEntity"),
        price_factor=float(row.get("factor", 1.0)),
    )


def propose(
    import_price: float | None,
    import_entity: str | None,
    export_price: float | None,
    export_entity: str | None,
) -> Tariff | None:
    """Tarif proposé d'après les prix du tableau Énergie de HA : prix dynamique si une entité de
    prix est déclarée, prix unique s'il y a un prix fixe ; ``None`` sans prix déclaré. À
    compléter par l'utilisateur (plages horaires, couleurs)."""
    base = import_price if import_price is not None else DEFAULT.base_eur_kwh
    if import_entity:
        tariff = Tariff(kind=TariffKind.DYNAMIC, base_eur_kwh=base, price_entity=import_entity)
    elif import_price is not None:
        tariff = Tariff(kind=TariffKind.SINGLE, base_eur_kwh=import_price)
    elif export_price is None and not export_entity:
        return None
    else:
        tariff = Tariff(kind=TariffKind.SINGLE, base_eur_kwh=base)
    return tariff.model_copy(
        update={"export_eur_kwh": export_price or 0.0, "export_entity": export_entity}
    )
