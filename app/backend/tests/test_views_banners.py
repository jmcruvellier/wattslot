"""Bandeaux des vues (lot 5.1, PR 3a) : départ, météo, charge complète, fraîcheur,
avertissements et explications, comparés au dashboard de la v1 d'origine."""

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from tests.test_views_day import PARIS, V1_CONTEXT, state_of
from tests.v1_oracle import STATES, v1
from wattslot.battery_settings import BatterySettings
from wattslot.views import banners
from wattslot.views.day import build_day
from wattslot.views.display import Context


@pytest.mark.parametrize("production", [0.0, 2.0, 4.9, 5.0, 9.0, 12.0])
def test_weather_quality_is_that_of_the_v1(production: float) -> None:
    expected = v1("dashboard._qualifier_meteo", production, 10.0)
    assert (
        banners.weather_quality(production, 10.0)
        == {
            "ensoleillee": "sunny",
            "mitigee": "mixed",
            "couverte": "cloudy",
            None: None,
        }[expected]
    )
    assert banners.weather_quality(production, None) is None


@pytest.mark.parametrize(
    ("midnight", "badge"), [(52.0, "ok"), (60.0, "medium"), (75.0, "large"), (None, None)]
)
def test_departure_compared_with_the_forecast_of_the_evening_before(
    midnight: float | None, badge: str | None
) -> None:
    state = {
        **state_of(STATES[0]),
        "depart_prevu": {"kwh": 2.56, "heure_iso": "2026-10-11T17:59:00+02:00"},
    }
    actual = {"soc_pct_minuit": midnight} if midnight is not None else {}
    found = banners.departure(state, actual, 5.12, 2.0, V1_CONTEXT)

    assert found.badge == badge
    html = v1(
        "dashboard._construire_bandeaux_jour",
        state,
        actual,
        5.12,
        2.0,
        [0.0] * 24,
        False,
        lang="fr",
    )
    assert f"{found.soc_kwh:.2f}" in html
    if badge is not None:
        assert f"({found.gap_points:+d} pts)" in html
        assert {"ok": "stat-badge-ok", "medium": "stat-badge-moyen", "large": "stat-badge-approx"}[
            badge
        ] in html


@pytest.mark.parametrize(
    ("last", "days", "priority"),
    [
        ("2026-10-12", 0, False),
        ("2026-10-11", 1, False),
        ("2026-10-06", 6, True),
        (None, None, True),
    ],
)
def test_last_full_charge(last: str | None, days: int | None, priority: bool) -> None:
    state = {
        "date_cible": date(2026, 10, 12),
        "historique_recent": {"derniere_charge_complete": last, "nb_jours": 30},
    }
    context = Context(battery=BatterySettings(full_charge_every_days=6))
    found = banners.full_charge(state, context)

    assert found is not None and (found.days, found.priority) == (days, priority)
    assert banners.full_charge({"date_cible": date(2026, 10, 12)}, context) is None


def test_tomorrow_weather_against_today() -> None:
    state = {**state_of(STATES[0]), "production_max_recente": {"max_kwh": 12.0, "nb_jours": 30}}
    production = [0.0] * 10 + [1.0] * 6 + [0.0] * 8  # 6 kWh
    found = banners.weather(state, None, production, "tomorrow", today_estimate_kwh=8.0)

    assert (found.quality, found.share_percent, found.today_gap_percent) == ("mixed", 50, -25)
    html = v1(
        "dashboard._construire_bandeau_demain",
        2.0,
        5.12,
        3.0,
        58.0,
        4.0,
        78.0,
        15,
        2.0,
        1.0,
        0.5,
        0.3,
        6.0,
        True,
        state["production_max_recente"],
        8.0,
        lang="fr",
    )
    assert "▼ -25%" in html and "50" in html


def test_yesterday_weather_uses_the_measured_production() -> None:
    state = {"production_max_recente": {"max_kwh": 10.0, "nb_jours": 30}}
    actual = {"production_reelle_horaire": {12: 4.0, 13: 4.0}}
    found = banners.weather(state, actual, [1.0] * 24, "yesterday")

    assert (found.production_kwh, found.measured, found.quality) == (8.0, True, "sunny")


def test_notices_and_freshness() -> None:
    state = {
        "avertissements": [
            {"code": "soc_depart_approximatif", "params": {}},
            {
                "code": "tache_reportee_sans_creneau",
                "params": {"equipement": "Lave-linge", "jour": "2026-10-18"},
            },
            "texte libre de la v1",
        ],
        "reports": [
            {
                "code": "tache_reportee",
                "params": {
                    "equipement": "Sèche-linge",
                    "jour": "2026-10-19",
                    "pct_jour": 80,
                    "pct_auj": 40,
                },
            }
        ],
    }
    tomorrow = banners.notices(state, "tomorrow")
    assert [n.code for n in tomorrow] == ["tache_reportee_sans_creneau", "texte", "tache_reportee"]
    assert tomorrow[-1].info and len(banners.notices(state, "today")) == 4
    assert tomorrow[0].text.startswith("Lave-linge reporté au")
    assert "18" in tomorrow[0].text and tomorrow[1].text == "texte libre de la v1"

    now = datetime(2026, 10, 17, 15, 0, tzinfo=PARIS)
    assert banners.freshness(now - timedelta(minutes=95), "today", now).minutes == 95  # type: ignore[union-attr]
    assert banners.freshness(now - timedelta(minutes=60), "today", now) is None
    stopped = banners.freshness(datetime(2026, 10, 16, 0, 1, tzinfo=PARIS), "yesterday", now)
    assert stopped is not None and stopped.code == "stopped_yesterday"


def test_the_view_carries_explanations_indicators_and_the_recommendation() -> None:
    state: dict[str, Any] = state_of(STATES[0])
    state["planning"] = [
        {**item, "explication": {"raisons": [{"code": "launched", "params": {"time": "10:42"}}]}}
        if "heure_debut" in item and item["equipement"] != "Batterie"
        else item
        for item in state["planning"]
    ]
    state["indicateurs"] = {"cout_eur": 1.23, "soutirage_kwh": 4.5, "injection_kwh": 0.7}
    view = build_day(state, "today", V1_CONTEXT, lang="en")

    assert view.indicators is not None and view.indicators.cost_eur == 1.23
    assert view.explanations and view.explanations[0].explanation.reasons[0].code == "launched"
    assert view.recommendation and view.weather.production_kwh > 0
    assert "10:42" in view.explanations[0].text  # rédigée en anglais
    assert view.departure is not None and view.departure.source == "plan"
