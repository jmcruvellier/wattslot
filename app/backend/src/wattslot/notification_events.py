"""Conditions et textes des notifications du catalogue (lot 5.6, PR 2), hors recommandation.

Chaque condition lit les plans gardés en base (format de la v1) et le bilan des équipements des
vues (lot 5.1), et renvoie ses candidates : une clé (équipement, cause…), le jour concerné et le
texte, dans la langue demandée. L'envoi, le journal (une seule fois par clé et par jour), les
heures de silence et l'appareil sont l'affaire de ``notifications``.

- « Lancez X maintenant » : un cycle prévu, pas encore lancé, démarre dans l'heure qui vient.
- Écart au plan : un cycle prévu n'a pas démarré 30 min après son heure, ou la production mesurée
  s'écarte de plus de 25 % de la prévision au relevé (badge « important » des vues).
- Batterie pleine avant midi : le plan prévoit 100 % avant 12 h, et cette heure est à venir.
- Prévision de demain qui chute : la production prévue pour demain a baissé de plus de 30 % par
  rapport à la plus haute prévision vue pour ce jour.

Le planning de la semaine (``week``) n'a pas de condition : c'est un texte, une ligne par jour à
venir de la vue Semaine, envoyé les jours choisis (``notifications``).
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from wattslot.languages import number
from wattslot.planning.warning_texts import catalog as warning_catalog
from wattslot.planning.warning_texts import hour_minutes, long_date
from wattslot.views.day import build_day
from wattslot.views.display import BATTERY, Context, find_item
from wattslot.views.week import WeekView

LATE_MIN = 30  # cycle prévu non lancé passé ce délai : écart au plan
NOW_MIN = 10  # « maintenant » : le cycle part dans ce délai ; au-delà, l'heure est dite
FULL_PERCENT = 99.5  # « pleine », aux arrondis de la simulation près
NOON = 12
DROP_PERCENT = 30

TEXTS: dict[str, dict[str, str]] = {
    "fr": {
        "device_now.title": "À lancer maintenant",
        "device_now": "Lancez {device} maintenant : son cycle est prévu à {time} ({kwh} kWh).",
        "device_soon": "Lancez {device} à {time} : son cycle est prévu à cette heure ({kwh} kWh).",
        "plan_gap.title": "Écart au plan",
        "plan_gap.cycle": "{device} n'a pas démarré : son cycle était prévu à {time}.",
        "plan_gap.production": (
            "Production solaire {direction} : {measured} kWh mesurés au relevé de {time}, "
            "{estimated} kWh prévus ({gap} %)."
        ),
        "plan_gap.above": "au-dessus de la prévision",
        "plan_gap.below": "en dessous de la prévision",
        "battery_full.title": "Batterie pleine avant midi",
        "battery_full": (
            "Batterie pleine prévue vers {time} : le surplus suivant partira sur le réseau, "
            "c'est le bon moment pour lancer un appareil."
        ),
        "forecast_drop.title": "Prévision de demain en baisse",
        "forecast_drop": (
            "Prévision de demain en baisse : {kwh} kWh de production, contre {reference} kWh "
            "prévus plus tôt ({gap} %)."
        ),
        "test": "[Essai] {message}",
        "week.title": "Planning de la semaine",
        "resources.title": "Ressources de WattSlot",
        "week.day": "{day} : {devices}",
        "week.device": "{device} {start}\u2013{end}",
        "week.nothing": "rien à lancer",
        "week.until": "Pas de prévision au-delà du {date}.",
    },
    "en": {
        "device_now.title": "Start now",
        "device_now": "Start the {device} now: its cycle is planned at {time} ({kwh} kWh).",
        "device_soon": "Start the {device} at {time}: its cycle is planned then ({kwh} kWh).",
        "plan_gap.title": "Off plan",
        "plan_gap.cycle": "The {device} has not started: its cycle was planned at {time}.",
        "plan_gap.production": (
            "Solar production {direction}: {measured} kWh measured at the {time} reading, "
            "{estimated} kWh forecast ({gap} %)."
        ),
        "plan_gap.above": "above the forecast",
        "plan_gap.below": "below the forecast",
        "battery_full.title": "Battery full before noon",
        "battery_full": (
            "Battery expected full around {time}: the next surplus will go to the grid, "
            "a good time to start an appliance."
        ),
        "forecast_drop.title": "Tomorrow's forecast drops",
        "forecast_drop": (
            "Tomorrow's forecast drops: {kwh} kWh of production, against {reference} kWh "
            "forecast earlier ({gap} %)."
        ),
        "test": "[Test] {message}",
        "week.title": "This week's plan",
        "resources.title": "WattSlot resources",
        "week.day": "{day}: {devices}",
        "week.device": "{device} {start}\u2013{end}",
        "week.nothing": "nothing to start",
        "week.until": "No forecast beyond {date}.",
    },
    # Allemand, néerlandais, espagnol, italien : préparés puis « à relire » (lot 5.7).
    "de": {
        "device_now.title": "Jetzt starten",
        "device_now": "Starten Sie {device} jetzt: Sein Zyklus ist um {time} geplant ({kwh} kWh).",
        "device_soon": "Starten Sie {device} um {time}: Sein Zyklus ist dann geplant ({kwh} kWh).",
        "plan_gap.title": "Abweichung vom Plan",
        "plan_gap.cycle": "{device} hat nicht begonnen: Sein Zyklus war um {time} geplant.",
        "plan_gap.production": (
            "Solarerzeugung {direction}: {measured} kWh bei der Messung um {time} gemessen, "
            "{estimated} kWh prognostiziert ({gap} %)."
        ),
        "plan_gap.above": "über der Prognose",
        "plan_gap.below": "unter der Prognose",
        "battery_full.title": "Batterie vor Mittag voll",
        "battery_full": (
            "Batterie voraussichtlich gegen {time} voll: Der nächste Überschuss geht ins Netz, "
            "ein guter Moment, ein Gerät zu starten."
        ),
        "forecast_drop.title": "Prognose für morgen sinkt",
        "forecast_drop": (
            "Prognose für morgen sinkt: {kwh} kWh Erzeugung, gegenüber {reference} kWh "
            "zuvor prognostiziert ({gap} %)."
        ),
        "test": "[Test] {message}",
        "week.title": "Wochenplan",
        "resources.title": "Ressourcen von WattSlot",
        "week.day": "{day}: {devices}",
        "week.device": "{device} {start}\u2013{end}",
        "week.nothing": "nichts zu starten",
        "week.until": "Keine Prognose über {date} hinaus.",
    },
    "nl": {
        "device_now.title": "Nu starten",
        "device_now": "Start {device} nu: de cyclus is gepland om {time} ({kwh} kWh).",
        "device_soon": "Start {device} om {time}: de cyclus is dan gepland ({kwh} kWh).",
        "plan_gap.title": "Afwijking van het plan",
        "plan_gap.cycle": "{device} is niet gestart: de cyclus was gepland om {time}.",
        "plan_gap.production": (
            "Zonneproductie {direction}: {measured} kWh gemeten bij de meting van {time}, "
            "{estimated} kWh voorspeld ({gap} %)."
        ),
        "plan_gap.above": "boven de prognose",
        "plan_gap.below": "onder de prognose",
        "battery_full.title": "Batterij vol vóór de middag",
        "battery_full": (
            "Batterij naar verwachting vol rond {time}: het volgende overschot gaat naar het net, "
            "een goed moment om een apparaat te starten."
        ),
        "forecast_drop.title": "Prognose voor morgen daalt",
        "forecast_drop": (
            "Prognose voor morgen daalt: {kwh} kWh productie, tegenover {reference} kWh "
            "eerder voorspeld ({gap} %)."
        ),
        "test": "[Test] {message}",
        "week.title": "Weekplanning",
        "resources.title": "Middelen van WattSlot",
        "week.day": "{day}: {devices}",
        "week.device": "{device} {start}\u2013{end}",
        "week.nothing": "niets te starten",
        "week.until": "Geen prognose na {date}.",
    },
    "es": {
        "device_now.title": "Póngalo ahora",
        "device_now": "Ponga {device} ahora: su ciclo está previsto a las {time} ({kwh} kWh).",
        "device_soon": "Ponga {device} a las {time}: su ciclo está previsto entonces ({kwh} kWh).",
        "plan_gap.title": "Desviación del plan",
        "plan_gap.cycle": "{device} no ha empezado: su ciclo estaba previsto a las {time}.",
        "plan_gap.production": (
            "Producción solar {direction}: {measured} kWh medidos en la lectura de las {time}, "
            "{estimated} kWh previstos ({gap} %)."
        ),
        "plan_gap.above": "por encima de la previsión",
        "plan_gap.below": "por debajo de la previsión",
        "battery_full.title": "Batería llena antes del mediodía",
        "battery_full": (
            "Batería llena prevista hacia las {time}: el siguiente excedente irá a la red, "
            "buen momento para poner un aparato."
        ),
        "forecast_drop.title": "La previsión de mañana baja",
        "forecast_drop": (
            "La previsión de mañana baja: {kwh} kWh de producción, frente a {reference} kWh "
            "previstos antes ({gap} %)."
        ),
        "test": "[Prueba] {message}",
        "week.title": "Planificación de la semana",
        "resources.title": "Recursos de WattSlot",
        "week.day": "{day}: {devices}",
        "week.device": "{device} {start}\u2013{end}",
        "week.nothing": "nada que poner",
        "week.until": "Sin previsión más allá del {date}.",
    },
    "it": {
        "device_now.title": "Da avviare ora",
        "device_now": "Avvii {device} ora: il suo ciclo è previsto alle {time} ({kwh} kWh).",
        "device_soon": "Avvii {device} alle {time}: il suo ciclo è previsto allora ({kwh} kWh).",
        "plan_gap.title": "Scostamento dal piano",
        "plan_gap.cycle": "{device} non è partito: il suo ciclo era previsto alle {time}.",
        "plan_gap.production": (
            "Produzione solare {direction}: {measured} kWh misurati alla lettura delle {time}, "
            "{estimated} kWh previsti ({gap} %)."
        ),
        "plan_gap.above": "sopra la previsione",
        "plan_gap.below": "sotto la previsione",
        "battery_full.title": "Batteria piena prima di mezzogiorno",
        "battery_full": (
            "Batteria piena prevista verso le {time}: il surplus successivo andrà in rete, "
            "buon momento per avviare un apparecchio."
        ),
        "forecast_drop.title": "La previsione di domani cala",
        "forecast_drop": (
            "La previsione di domani cala: {kwh} kWh di produzione, contro {reference} kWh "
            "previsti prima ({gap} %)."
        ),
        "test": "[Prova] {message}",
        "week.title": "Programma della settimana",
        "resources.title": "Risorse di WattSlot",
        "week.day": "{day}: {devices}",
        "week.device": "{device} {start}\u2013{end}",
        "week.nothing": "niente da avviare",
        "week.until": "Nessuna previsione oltre {date}.",
    },
}


def text(lang: str, key: str, **params: Any) -> str:
    return TEXTS[lang if lang in TEXTS else "fr"][key].format(**params)


def clock(minutes: float, lang: str) -> str:
    """« 10h05 » / « 10:05 »."""
    h, m = divmod(round(minutes), 60)
    return f"{h % 24}h{m:02d}" if lang == "fr" else f"{h % 24}:{m:02d}"


def _signed(value: float) -> str:
    return f"{value:+.0f}"


@dataclass(frozen=True)
class Candidate:
    key: str
    day: str
    message: str


def _day(state: Mapping[str, Any]) -> str:
    return str(state.get("date_cible"))


def _today_view(state: Mapping[str, Any], zone: Any, lang: str) -> Any:
    return build_day(state, "today", Context(zone=zone), lang)


def device_now(
    state: Mapping[str, Any],
    local: datetime,
    lang: str,
    next_run_min: int | None = None,
    declared: Set[str] = frozenset(),
) -> list[Candidate]:
    """Cycles à lancer d'ici une heure. ``next_run_min`` : minutes d'ici le prochain calcul ; un
    cycle qui part après lui attend ce calcul, plus proche de son heure (le calcul de 0 h 01
    disait « maintenant » pour un cycle de 1 h, que celui de 0 h 59 annonce une minute avant).
    Un départ à plus de ``NOW_MIN`` minutes dit son heure, pas « maintenant ». ``declared`` :
    appareils déclarés lancés par l'utilisateur (« C'est lancé »), qui ne sont plus à annoncer."""
    view = _today_view(state, local.tzinfo, lang)
    cycles = {row.device for row in view.timeline.rows if row.kind == "cycle"}
    now_min = local.hour * 60 + local.minute
    window = 60 if next_run_min is None else min(60, next_run_min)
    return [
        Candidate(
            key=f"{status.device}@{status.planned_start_min}",
            day=_day(state),
            message=text(
                lang,
                "device_now" if status.planned_start_min - now_min <= NOW_MIN else "device_soon",
                device=status.device,
                time=clock(status.planned_start_min, lang),
                kwh=number(status.planned_kwh, lang, 1),
            ),
        )
        for status in view.timeline.statuses
        if status.device in cycles
        and status.device not in declared
        and status.status == "planned"
        and now_min < status.planned_start_min <= now_min + window
    ]


def plan_gap(state: Mapping[str, Any], local: datetime, lang: str) -> list[Candidate]:
    actual = state.get("donnees_reelles_cache") or None
    if not actual:
        return []  # sans relevé, rien à comparer
    view = _today_view(state, local.tzinfo, lang)
    reading = view.actual_updated_at.astimezone(local.tzinfo) if view.actual_updated_at else local
    reading_min = reading.hour * 60 + reading.minute
    cycles = {row.device for row in view.timeline.rows if row.kind == "cycle"}
    found = [
        Candidate(
            key=f"cycle:{status.device}@{status.planned_start_min}",
            day=_day(state),
            message=text(
                lang,
                "plan_gap.cycle",
                device=status.device,
                time=clock(status.planned_start_min, lang),
            ),
        )
        for status in view.timeline.statuses
        if status.device in cycles
        and (
            status.status == "no_cycle"
            or (status.status == "planned" and reading_min >= status.planned_start_min + LATE_MIN)
        )
    ]
    weather = view.cards.weather if view.cards else None
    if weather is not None and weather.badge == "important" and weather.gap_percent is not None:
        found.append(
            Candidate(
                key="production",
                day=_day(state),
                message=text(
                    lang,
                    "plan_gap.production",
                    direction=text(
                        lang, "plan_gap.above" if weather.gap_percent > 0 else "plan_gap.below"
                    ),
                    measured=number(weather.measured_kwh or 0, lang, 1),
                    estimated=number(weather.estimated_kwh or 0, lang, 1),
                    gap=_signed(weather.gap_percent),
                    time=clock(reading_min, lang),
                ),
            )
        )
    return found


def battery_full(state: Mapping[str, Any], local: datetime, lang: str) -> list[Candidate]:
    battery = find_item(state.get("planning", []), BATTERY) or {}
    capacity = state.get("capacite_batterie_kwh") or 0
    by_hour = battery.get("soc_horaire_kwh") or {}
    if not capacity or not by_hour:
        return []
    for hour in range(NOON):
        kwh = by_hour.get(hour, by_hour.get(str(hour)))
        if kwh is not None and kwh / capacity * 100 >= FULL_PERCENT:
            # Utile seulement avant : pleine à la fin de cette heure (SoC horaire de fin d'heure).
            if local.hour > hour:
                return []
            return [
                Candidate(
                    key="noon",
                    day=_day(state),
                    message=text(lang, "battery_full", time=clock((hour + 1) * 60, lang)),
                )
            ]
    return []


def tomorrow_production(state: Mapping[str, Any]) -> float:
    return float(sum((state.get("production_solaire_horaire") or {}).values()))


def forecast_drop(
    state: Mapping[str, Any], reference_kwh: float | None, lang: str
) -> list[Candidate]:
    """``reference_kwh`` : la plus haute prévision vue jusque-là pour ce jour."""
    kwh = tomorrow_production(state)
    if not reference_kwh or reference_kwh <= 0:
        return []
    gap = (kwh - reference_kwh) / reference_kwh * 100
    if gap > -DROP_PERCENT:
        return []
    return [
        Candidate(
            key="tomorrow",
            day=_day(state),
            message=text(
                lang,
                "forecast_drop",
                kwh=number(kwh, lang, 1),
                reference=number(reference_kwh, lang, 1),
                gap=_signed(gap),
            ),
        )
    ]


def _short_date(day: date, lang: str) -> str:
    """« Lundi 9 Novembre », « Monday, November 9 » : format des catalogues des avertissements."""
    names: dict[str, str] = warning_catalog(lang)["date"]
    return names["format_sans_annee"].format(
        jour=names[f"jour_{day.weekday()}"], num=day.day, mois=names[f"mois_{day.month}"]
    )


def week(view: WeekView, local: datetime, lang: str) -> str | None:
    """Planning de la semaine : une ligne par jour à venir, ses appareils et leurs heures.
    Aujourd'hui, seulement les cycles pas encore commencés, et pas de ligne s'il n'en reste
    aucun ; ``None`` sans aucun jour à venir. Un horizon arrêté plus tôt est signalé."""
    today = local.date()
    now_min = local.hour * 60 + local.minute
    lines: list[str] = []
    for found in view.days:
        devices = sorted(found.devices, key=lambda d: d.start_min)
        if found.day < today:
            continue
        if found.day == today:
            devices = [d for d in devices if d.start_min > now_min]
            if not devices:
                continue
        listed = ", ".join(
            text(
                lang,
                "week.device",
                device=d.device,
                start=hour_minutes(d.start_min, lang),
                end=hour_minutes(d.end_min, lang),
            )
            for d in devices
        )
        lines.append(
            text(
                lang,
                "week.day",
                day=_short_date(found.day, lang),
                devices=listed or text(lang, "week.nothing"),
            )
        )
    if not lines:
        return None
    if view.missing_days:
        last = min(view.missing_days) - timedelta(days=1)
        lines.append(text(lang, "week.until", date=long_date(last, lang)))
    return "\n".join(lines)
