"""« En ce moment » et prochaine action de la vue Aujourd'hui (lot 6b.3).

Les flux du moment viennent du dernier quart d'heure clos des agrégats (lot 1.3) : production,
achat, surplus, charge et décharge de la batterie, en puissance moyenne ; la consommation de la
maison en est le bilan. Le niveau de la batterie est la dernière valeur relevée. Une phrase
résume le moment, dans la langue demandée ; sans quart d'heure récent, ni flux ni phrase.

La prochaine action est le prochain appareil à cycle encore à venir dans le plan du jour, avec
son explication (« Pourquoi ce plan »).
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from wattslot import home_model
from wattslot.aggregation import PERIODS, QUARTER
from wattslot.detection import Role
from wattslot.languages import Language
from wattslot.planning.plan import Explanation
from wattslot.views.display import Context
from wattslot.views.timeline import Timeline

QUARTER_LENGTH = PERIODS[QUARTER]
# Au-delà, le dernier quart d'heure clos ne dit plus le moment (agrégation arrêtée, HA coupé).
STALE_AFTER = timedelta(minutes=30)
NIGHT_W = 50.0  # production en dessous : la nuit, ou presque

FLOWS = {
    Role.ENERGY_PRODUCED: "production_w",
    Role.ENERGY_IMPORTED: "import_w",
    Role.ENERGY_EXPORTED: "export_w",
    Role.ENERGY_CHARGED: "charge_w",
    Role.ENERGY_DISCHARGED: "discharge_w",
}


class Now(BaseModel):
    """Le moment : puissances moyennes du dernier quart d'heure clos, en watts."""

    since: datetime | None = None  # début du quart d'heure
    until: datetime | None = None  # fin du quart d'heure
    production_w: float | None = None
    consumption_w: float | None = None  # bilan de la maison
    battery_w: float | None = None  # positive en charge, négative en décharge
    grid_w: float | None = None  # positive à l'achat, négative au surplus
    soc_percent: float | None = None  # dernier relevé
    off_peak: bool = False
    sentence: str | None = None


class OtherStart(BaseModel):
    """Autre départ permis du prochain appareil, à choisir (écarts par rapport au plan)."""

    start_min: int
    end_min: int
    cost_eur_delta: float
    import_kwh_delta: float


class NextAction(BaseModel):
    device: str
    start_min: int  # minutes depuis minuit, heure locale
    end_min: int
    explanation: str | None = None
    # Autres départs proposés par le plan, les meilleurs d'abord, et départ choisi par
    # l'utilisateur (« Revenir au choix du calcul »).
    alternatives: list[OtherStart] = []
    chosen: bool = False
    # « Me le rappeler » (lot 6b.3) : rappel posé, et service de notification réglé.
    reminder: bool = False
    can_remind: bool = False


TEXTS: dict[str, dict[str, str]] = {
    "fr": {
        "sun_share": "Le soleil couvre {share} % de la maison",
        "sun_all_battery": "Le soleil couvre toute la maison, le surplus charge la batterie",
        "sun_all_grid": "Le soleil couvre toute la maison, le surplus part sur le réseau",
        "battery": "La batterie alimente la maison",
        "grid_off_peak": "La maison tire sur le réseau, en heures creuses",
        "grid_peak": "La maison tire sur le réseau, en heures pleines",
    },
    "en": {
        "sun_share": "The sun covers {share}% of the home",
        "sun_all_battery": "The sun covers the whole home, the surplus charges the battery",
        "sun_all_grid": "The sun covers the whole home, the surplus goes to the grid",
        "battery": "The battery is powering the home",
        "grid_off_peak": "The home is drawing from the grid, at off-peak rate",
        "grid_peak": "The home is drawing from the grid, at peak rate",
    },
    "de": {
        "sun_share": "Die Sonne deckt {share} % des Hauses",
        "sun_all_battery": "Die Sonne deckt das ganze Haus, der Überschuss lädt die Batterie",
        "sun_all_grid": "Die Sonne deckt das ganze Haus, der Überschuss geht ins Netz",
        "battery": "Die Batterie versorgt das Haus",
        "grid_off_peak": "Das Haus bezieht Strom aus dem Netz, im Niedertarif",
        "grid_peak": "Das Haus bezieht Strom aus dem Netz, im Hochtarif",
    },
    "nl": {
        "sun_share": "De zon dekt {share}% van het huis",
        "sun_all_battery": "De zon dekt het hele huis, het overschot laadt de batterij",
        "sun_all_grid": "De zon dekt het hele huis, het overschot gaat naar het net",
        "battery": "De batterij voedt het huis",
        "grid_off_peak": "Het huis neemt stroom van het net, in het daltarief",
        "grid_peak": "Het huis neemt stroom van het net, in het piektarief",
    },
    "es": {
        "sun_share": "El sol cubre el {share} % de la casa",
        "sun_all_battery": "El sol cubre toda la casa, el excedente carga la batería",
        "sun_all_grid": "El sol cubre toda la casa, el excedente va a la red",
        "battery": "La batería alimenta la casa",
        "grid_off_peak": "La casa toma energía de la red, en horas valle",
        "grid_peak": "La casa toma energía de la red, en horas punta",
    },
    "it": {
        "sun_share": "Il sole copre il {share}% della casa",
        "sun_all_battery": "Il sole copre tutta la casa, il surplus carica la batteria",
        "sun_all_grid": "Il sole copre tutta la casa, il surplus va in rete",
        "battery": "La batteria alimenta la casa",
        "grid_off_peak": "La casa preleva dalla rete, in fascia economica",
        "grid_peak": "La casa preleva dalla rete, in fascia di punta",
    },
}


def sentence(flows: Mapping[str, float], off_peak: bool, lang: Language) -> str | None:
    """Phrase du moment d'après les puissances moyennes du quart d'heure ; ``None`` sans
    production ni achat mesurés."""
    texts = TEXTS[lang]
    production = flows.get("production_w")
    consumption = flows.get("consumption_w")
    if production is None or consumption is None or consumption <= 0:
        return None
    if production < NIGHT_W:
        if flows.get("discharge_w", 0.0) > flows.get("import_w", 0.0):
            return texts["battery"]
        return texts["grid_off_peak" if off_peak else "grid_peak"]
    if production >= consumption:
        surplus_to_battery = flows.get("charge_w", 0.0) >= flows.get("export_w", 0.0)
        return texts["sun_all_battery" if surplus_to_battery else "sun_all_grid"]
    return texts["sun_share"].format(share=round(100 * production / consumption))


def measure_now(state: Any, moment: datetime, context: Context, lang: Language) -> Now:
    """Le moment d'après le dernier quart d'heure clos ; ``state`` : l'état de l'application."""
    local = moment.astimezone(context.zone)
    found = Now(off_peak=context.off_peak_hours()[local.hour], soc_percent=_soc(state))
    aggregator = getattr(state, "aggregator", None)
    if aggregator is None:
        return found
    until = aggregator.status().complete_until.get(QUARTER)
    if until is None or moment - until > STALE_AFTER:
        return found
    since = until - QUARTER_LENGTH
    flows: dict[str, float] = {}
    for device in home_model.load(state.graph).devices:
        for sensor in device.sensors:
            key = FLOWS.get(sensor.role)
            if key is None:
                continue
            for aggregate in aggregator.read(sensor.entity_id, QUARTER, since, until):
                if aggregate.energy_kwh is not None:
                    # kWh sur 15 minutes → puissance moyenne en watts.
                    watts = aggregate.energy_kwh * 1000 * (timedelta(hours=1) / QUARTER_LENGTH)
                    flows[key] = flows.get(key, 0.0) + watts
    if "production_w" not in flows and "import_w" not in flows:
        return found
    flows["consumption_w"] = max(
        0.0,
        flows.get("production_w", 0.0)
        + flows.get("import_w", 0.0)
        - flows.get("export_w", 0.0)
        + flows.get("discharge_w", 0.0)
        - flows.get("charge_w", 0.0),
    )
    has_battery = "charge_w" in flows or "discharge_w" in flows
    has_grid = "import_w" in flows or "export_w" in flows
    return found.model_copy(
        update={
            "since": since,
            "until": until,
            "production_w": round(flows["production_w"]) if "production_w" in flows else None,
            "consumption_w": round(flows["consumption_w"]),
            "battery_w": (
                round(flows.get("charge_w", 0.0) - flows.get("discharge_w", 0.0))
                if has_battery
                else None
            ),
            "grid_w": (
                round(flows.get("import_w", 0.0) - flows.get("export_w", 0.0)) if has_grid else None
            ),
            "sentence": sentence(flows, found.off_peak, lang),
        }
    )


def _soc(state: Any) -> float | None:
    ingestor = getattr(state, "ingestor", None)
    if ingestor is None:
        return None
    values = [
        e.last_value
        for e in ingestor.status().entities
        if e.role is Role.STATE_OF_CHARGE and e.last_value is not None
    ]
    return round(values[0]) if values else None


def next_action(
    timeline: Timeline,
    explanations: Mapping[str, str],
    moment: datetime,
    context: Context,
    details: Mapping[str, Explanation] | None = None,
) -> NextAction | None:
    """Prochain appareil à cycle à lancer d'après le plan du jour : pas encore lancé, et dont la
    plage n'est pas finie."""
    local = moment.astimezone(context.zone)
    now_min = local.hour * 60 + local.minute
    cycles = {row.device for row in timeline.rows if row.kind == "cycle"}
    upcoming = [
        status
        for status in timeline.statuses
        if status.device in cycles
        and status.status == "planned"
        and status.planned_end_min > now_min
    ]
    if not upcoming:
        return None
    first = min(upcoming, key=lambda status: status.planned_start_min)
    detail = (details or {}).get(first.device)
    length = first.planned_end_min - first.planned_start_min
    return NextAction(
        device=first.device,
        start_min=first.planned_start_min,
        end_min=first.planned_end_min,
        explanation=explanations.get(first.device),
        # Départs à venir seulement : un départ déjà passé ne se choisit plus.
        alternatives=[
            OtherStart(
                start_min=a.start_min,
                end_min=a.start_min + length,
                cost_eur_delta=a.cost_eur_delta,
                import_kwh_delta=a.import_kwh_delta,
            )
            for a in (detail.alternatives if detail else [])
            if a.start_min > now_min
        ],
        chosen=bool(detail and detail.chosen),
    )
