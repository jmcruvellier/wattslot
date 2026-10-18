"""Bandeaux, avertissements et explications d'une vue (lot 5.1, PR 3a).

Bandeaux « départ » et « météo » des vues Aujourd'hui, Hier et Demain, rappel de la dernière
charge complète, fraîcheur des calculs : ``_construire_bandeaux_jour``,
``_construire_bandeau_demain``, ``_texte_charge_complete``, ``_qualifier_meteo`` et la fraîcheur
de ``generer_html_dashboard`` (v1), en données. Les textes sont des codes avec paramètres.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from wattslot.planning.explain import render
from wattslot.planning.plan import Explanation, Plan
from wattslot.planning.warning_texts import warning_text
from wattslot.views.display import Context, recalculated_production

SUNNY = 0.70  # part de la meilleure production des 30 derniers jours
MIXED = 0.35
DEPARTURE_OK_PTS = 5  # écart du SoC de départ à la prévision de la veille
DEPARTURE_GAP_PTS = 15
STALE_TODAY_MIN = 90  # plus de 90 min sans calcul : une exécution a été sautée
YESTERDAY_LAST_HOUR = 20  # archive d'Hier arrêtée avant 20 h : calculs interrompus

Weather = Literal["sunny", "mixed", "cloudy"]
_WEATHER = {"ensoleillee": "sunny", "mitigee": "mixed", "couverte": "cloudy"}


class FullCharge(BaseModel):
    """Dernière charge complète de la batterie."""

    days: int | None  # jours depuis ; aucune connue sur l'historique : ``None``
    history_days: int | None = None  # jours d'historique, sans charge complète
    priority: bool  # au-delà de la périodicité réglée : journée prioritaire


class Departure(BaseModel):
    """SoC de départ à minuit."""

    soc_kwh: float
    soc_percent: float
    source: Literal["measured", "plan", "tonight", "now"]  # Demain : ce soir ou maintenant
    expected_kwh: float | None = None  # prévu la veille au soir
    expected_percent: float | None = None
    expected_at: datetime | None = None
    gap_points: int | None = None
    badge: Literal["ok", "medium", "large", "reliable", "approximate"] | None = None
    full_charge: FullCharge | None = None


class WeatherBanner(BaseModel):
    production_kwh: float
    measured: bool  # production mesurée (Hier) plutôt que prévue
    quality: Weather | None  # aucune : pas de référence exploitable
    share_percent: int | None = None  # part de la meilleure production récente
    best_kwh: float | None = None
    best_days: int | None = None
    today_estimate_kwh: float | None = None  # Demain : production estimée d'aujourd'hui
    today_gap_percent: int | None = None


class Notice(BaseModel):
    """Avertissement du plan (code et paramètres, ``avertissement.*``) ou information."""

    code: str
    params: dict[str, Any] = {}
    info: bool = False  # tâche reportée : information plutôt qu'avertissement
    text: str = ""  # rédigé dans la langue demandée (noms, heures, durées, dates mis en forme)


class Freshness(BaseModel):
    code: Literal["stale_today", "stopped_yesterday"]
    minutes: int | None = None  # depuis le dernier calcul (Aujourd'hui)
    last_at: datetime | None = None  # dernier calcul de la journée (Hier)


class Indicators(BaseModel):
    """Indicateurs du plan (lot 3.6), sous des noms anglais : ceux du plan typé gardent les
    clés de la v1 en alias, que l'API sérialiserait."""

    cost_eur: float
    import_kwh: float
    export_kwh: float
    self_consumption_percent: float | None = None
    end_soc_percent: float | None = None
    battery_throughput_kwh: float = 0.0
    co2_kg: float | None = None


class DeviceExplanation(BaseModel):
    device: str
    explanation: Explanation
    text: str = ""  # rédigée dans la langue demandée


def weather_quality(production_kwh: float, best_kwh: float | None) -> Weather | None:
    """Ensoleillée, mitigée ou couverte (``_qualifier_meteo``)."""
    if not best_kwh or best_kwh <= 0:
        return None
    share = production_kwh / best_kwh
    if share >= SUNNY:
        return "sunny"
    if share >= MIXED:
        return "mixed"
    return "cloudy"


def full_charge(state: Mapping[str, Any], context: Context) -> FullCharge | None:
    """Dernière charge complète (``_texte_charge_complete`` et ``_contexte_priorite_batterie``)."""
    day = state.get("date_cible")
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day)
        except ValueError:
            return None
    history = state.get("historique_recent") or {}
    if not history or not isinstance(day, date):
        return None
    every = context.battery.full_charge_every_days or 10**6
    last = history.get("derniere_charge_complete")
    days = (day - date.fromisoformat(last)).days if last else (history.get("nb_jours") or every) + 1
    return FullCharge(
        days=max(days, 0) if last else None,
        history_days=None if last else history.get("nb_jours"),
        priority=days >= every,
    )


def _round_half_even(value: float) -> int:
    return round(value)  # même arrondi que la v1 (``round`` de Python)


def departure(
    state: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    capacity_kwh: float,
    initial_kwh: float,
    context: Context,
) -> Departure:
    """Départ des vues Aujourd'hui et Hier (``_construire_bandeaux_jour``)."""

    def percent(kwh: float) -> float:
        return kwh / capacity_kwh * 100 if capacity_kwh else 0

    midnight = (actual or {}).get("soc_pct_minuit")
    if midnight is not None:
        found = Departure(
            soc_kwh=round(midnight / 100 * capacity_kwh, 3),
            soc_percent=round(midnight, 1),
            source="measured",
        )
    else:
        found = Departure(
            soc_kwh=round(initial_kwh, 3), soc_percent=round(percent(initial_kwh), 1), source="plan"
        )
    expected = state.get("depart_prevu")
    if expected and expected.get("kwh") is not None:
        found.expected_kwh = round(expected["kwh"], 3)
        found.expected_percent = round(percent(expected["kwh"]), 1)
        if expected.get("heure_iso"):
            found.expected_at = datetime.fromisoformat(expected["heure_iso"])
        if midnight is not None:
            gap = _round_half_even(midnight - percent(expected["kwh"]))
            found.gap_points = gap
            found.badge = (
                "ok"
                if abs(gap) <= DEPARTURE_OK_PTS
                else "medium"
                if abs(gap) <= DEPARTURE_GAP_PTS
                else "large"
            )
    found.full_charge = full_charge(state, context)
    return found


def tomorrow_departure(
    state: Mapping[str, Any], capacity_kwh: float, initial_kwh: float, context: Context
) -> Departure:
    """Départ de la vue Demain : SoC prévu ce soir (fiable), ou SoC actuel (approximatif)."""
    approximate = any(
        isinstance(w, dict) and w.get("code") == "soc_depart_approximatif"
        for w in state.get("avertissements", [])
    )
    return Departure(
        soc_kwh=round(initial_kwh, 3),
        soc_percent=round(initial_kwh / capacity_kwh * 100 if capacity_kwh else 0, 1),
        source="now" if approximate else "tonight",
        badge="approximate" if approximate else "reliable",
        full_charge=full_charge(state, context),
    )


def weather(
    state: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    production: Sequence[float],
    kind: str,
    today_estimate_kwh: float | None = None,
) -> WeatherBanner:
    """Bandeau météo : production de référence (mesurée Hier ; mesurée puis prévue Aujourd'hui ;
    prévue Demain), qualifiée par la meilleure production des 30 derniers jours."""
    measured_by_hour = (actual or {}).get("production_reelle_horaire")
    measured = False
    if kind == "yesterday" and measured_by_hour:
        reference, measured = float(sum(measured_by_hour.values())), True
    elif kind == "today":
        recalculated = recalculated_production(production, actual)
        reference = recalculated if recalculated is not None else float(sum(production))
    else:
        reference = float(sum(production))
    best = state.get("production_max_recente") or {}
    best_kwh = best.get("max_kwh")
    quality = weather_quality(reference, best_kwh)
    found = WeatherBanner(
        production_kwh=round(reference, 3),
        measured=measured,
        quality=quality,
        share_percent=_round_half_even(reference / best_kwh * 100)
        if quality and best_kwh
        else None,
        best_kwh=best_kwh if quality else None,
        best_days=best.get("nb_jours") if quality else None,
    )
    if kind == "tomorrow" and today_estimate_kwh and today_estimate_kwh > 0:
        found.today_estimate_kwh = round(today_estimate_kwh, 3)
        found.today_gap_percent = _round_half_even(
            (reference - today_estimate_kwh) / today_estimate_kwh * 100
        )
    return found


def notices(state: Mapping[str, Any], kind: str, lang: str = "fr") -> list[Notice]:
    """Avertissements du plan, puis tâches reportées (information). En vue Demain, le départ
    approximatif est porté par le bandeau « départ »."""
    found = []
    for warning in state.get("avertissements", []):
        if isinstance(warning, dict):
            if kind == "tomorrow" and warning.get("code") == "soc_depart_approximatif":
                continue
            found.append(
                Notice(
                    code=warning["code"],
                    params=warning.get("params") or {},
                    text=warning_text(warning, lang),
                )
            )
        else:
            found.append(Notice(code="texte", params={"texte": str(warning)}, text=str(warning)))
    for report in state.get("reports") or []:
        if isinstance(report, dict):
            found.append(
                Notice(
                    code=report["code"],
                    params=report.get("params") or {},
                    info=True,
                    text=warning_text(report, lang),
                )
            )
    return found


def freshness(computed_at: datetime | None, kind: str, now: datetime) -> Freshness | None:
    """Calculs interrompus : plus de 90 min sans calcul Aujourd'hui, archive d'Hier arrêtée
    avant 20 h."""
    if computed_at is None:
        return None
    if kind == "today":
        minutes = int((now - computed_at).total_seconds() / 60)
        if minutes > STALE_TODAY_MIN:
            return Freshness(code="stale_today", minutes=minutes)
    elif kind == "yesterday" and computed_at.hour < YESTERDAY_LAST_HOUR:
        return Freshness(code="stopped_yesterday", last_at=computed_at)
    return None


def as_stored(state: Mapping[str, Any]) -> dict[str, Any]:
    """Plan avec sa date en texte, comme relu en base (les états de la v1 la portent en date)."""
    day = state.get("date_cible")
    return {**state, "date_cible": day.isoformat()} if isinstance(day, date) else dict(state)


def explanations(
    state: Mapping[str, Any], lang: str = "fr"
) -> tuple[Indicators | None, list[DeviceExplanation]]:
    """Indicateurs du plan (lot 3.6) et explications de chaque équipement (lot 3.7)."""
    plan = Plan.from_v1(as_stored(state))
    found = []
    for item in plan.items:
        explanation = getattr(item, "explanation", None)
        device = getattr(item, "device", None)
        if explanation is not None and device:
            found.append(
                DeviceExplanation(
                    device=device, explanation=explanation, text=render(explanation, lang)
                )
            )
    indicators = plan.indicators
    if indicators is None:
        return None, found
    return Indicators.model_validate(
        indicators.model_dump(include=set(Indicators.model_fields))
    ), found
