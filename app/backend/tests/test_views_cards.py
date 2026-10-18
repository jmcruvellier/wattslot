"""Cartes estimé / mesuré au relevé (lot 5.1, PR 3b), reprises du JavaScript de la page de la v1
(``majCartesResume``, ``majLignesJournee``, ``majBandeauMeteo``, ``majTendance``)."""

from typing import Any

import pytest

from tests.test_views_day import V1_CONTEXT, actual_of, state_of
from tests.v1_oracle import STATES
from wattslot.views.cards import build_cards, cumulated, reading_weather, trend
from wattslot.views.day import build_day


@pytest.mark.parametrize(
    ("estimated", "measured", "inverse", "zero", "expected"),
    [
        (2.0, 2.01, False, False, ("stable", 0, None)),
        (2.0, 2.5, False, False, ("up", 25, True)),
        (2.0, 2.5, True, False, ("up", 25, False)),  # réseau : plus que prévu, défavorable
        (2.0, 1.5, False, False, ("down", -25, False)),
        (0.0, 0.2, True, True, ("infinite", None, False)),  # surplus imprévu
        (0.0, 0.2, False, True, ("infinite", None, True)),  # charge imprévue
        (0.0, 0.001, False, True, ("stable", 0, None)),
        (None, 1.0, False, False, ("none", None, None)),
        (0.0, 1.0, False, False, ("none", None, None)),
    ],
)
def test_trend(
    estimated: float | None, measured: float, inverse: bool, zero: bool, expected: tuple[Any, ...]
) -> None:
    found = trend(estimated, measured, inverse, zero)
    assert (found.direction, found.percent, found.favorable) == expected


def test_cumulated_forecast_counts_the_current_hour_pro_rata() -> None:
    series = [1.0] * 24
    assert cumulated(series, 10.5) == 10.5
    assert cumulated(series, 24) == 24


@pytest.mark.parametrize(
    ("measured", "estimated", "badge", "gap"),
    [
        (5.4, 5.0, "reliable", 8),
        (6.0, 5.0, "moderate", 20),
        (7.0, 5.0, "important", 40),
        (0.5, 0.6, "too_early", None),
    ],
)
def test_weather_reliability_at_the_reading(
    measured: float, estimated: float, badge: str, gap: int | None
) -> None:
    found = reading_weather("today", estimated, measured, None)
    assert (found.mode, found.badge, found.gap_percent) == ("reading", badge, gap)
    assert reading_weather("today", 5.0, None, None).mode == "no_reading"


def test_today_cards_at_the_reading() -> None:
    state = state_of(STATES[0])
    actual = {
        **actual_of(state, hour=14),
        "soc_pct_minuit": 99.0,
        "batterie_reelle_segments": [{"action": "charge", "energie_kwh": 1.5}],
        "reseau_reel_soutire_horaire": {8: 0.4, 9: 0.3},
        "reseau_reel_injecte_horaire": {13: 0.2},
    }
    view = build_day({**state, "donnees_reelles_cache": actual}, "today", V1_CONTEXT)
    cards = view.cards
    assert cards is not None and cards.reference_hour == pytest.approx(14 + 20 / 60, abs=1e-3)
    lines = {line.key: line for line in cards.at_reading}

    production = [p.production_kwh for p in view.hours]
    assert lines["production"].estimated_kwh == pytest.approx(
        cumulated(production, 14 + 1 / 3), abs=1e-3
    )
    measured = sum(actual["production_reelle_horaire"].values())
    assert lines["production"].measured_kwh == pytest.approx(measured, abs=1e-3)
    assert lines["grid_import"].measured_kwh == 0.7 and lines["charge"].measured_kwh == 1.5
    # SoC max mesuré : départ à minuit plus haut que les fins d'heure.
    assert (lines["soc_max"].measured_percent, lines["soc_max"].measured_hour) == (99.0, 0.0)

    day = {line.key: line for line in cards.day or []}
    rest = cumulated(production, 24) - cumulated(production, 14 + 1 / 3)
    assert day["production"].measured_kwh == pytest.approx(measured + rest, abs=1e-3)
    assert cards.weather is not None and cards.weather.mode == "reading"


def test_yesterday_compares_the_measures_with_the_first_forecast() -> None:
    state = state_of(STATES[0])
    initial = {
        "soc_final_kwh": 2.5,
        "soc_final_pct": 48.8,
        "soc_max_kwh": 5.0,
        "soc_max_pct": 97.7,
        "heure_soc_max": 15,
        "charge_total": 3.0,
        "decharge_total": 2.0,
        "soutire_total": 1.0,
        "injecte_total": 0.5,
        "production_totale": 9.0,
        "heure_iso": "2026-10-12T00:01:00+02:00",
    }
    actual = {**actual_of(state, hour=23), "production_reelle_horaire": {12: 4.5, 13: 4.5}}
    cards = build_cards(
        state,
        actual,
        "yesterday",
        24.0,
        [50.0] * 24,
        {
            k: [0.0] * 24
            for k in ("charge", "discharge", "grid_import", "grid_export", "production")
        },
        {},
        initial,
        {"soc_initial_kwh": 2.0},
    )
    lines = {line.key: line for line in cards.at_reading}

    assert lines["soc"].estimated_kwh == 2.5 and lines["production"].estimated_kwh == 9.0
    assert (lines["soc_max"].estimated_kwh, lines["soc_max"].estimated_hour) == (5.0, 15.0)
    assert lines["production"].trend.direction == "stable" and cards.day is None
    assert cards.weather is not None and cards.weather.mode == "day"


def test_tomorrow_has_no_cards() -> None:
    assert build_day(state_of(STATES[0]), "tomorrow", V1_CONTEXT).cards is None
