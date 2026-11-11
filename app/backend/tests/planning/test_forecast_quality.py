"""Qualité des prévisions : données gardées au calcul, critères et note à l'affichage."""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from wattslot.planning import past
from wattslot.planning.forecast_quality import (
    STORED_KEY,
    BaselineQuality,
    assess,
    spread_percent,
    stored,
)

TARGET = date(2026, 11, 11)  # un mercredi


def flows(days: list[date], kwh: dict[date, float] | None = None) -> past._Flows:
    """Achats horaires de ``days`` (1 kWh par heure, ou ``kwh[jour] / 24``), sans le reste."""
    imported: dict[date, dict[int, float]] = defaultdict(dict)
    for day in days:
        for hour in range(24):
            imported[day][hour] = (kwh or {}).get(day, 24.0) / 24
    return past._Flows(
        produced={},
        imported=dict(imported),
        exported={},
        charged={},
        discharged={},
        appliances={},
        has_battery=False,
    )


def test_six_same_weekdays_make_a_full_baseline() -> None:
    weeks = [TARGET - timedelta(weeks=k) for k in range(1, 8)]
    detail = past._typical_detail(flows(weeks), TARGET, 6)
    assert detail.quality.days_per_hour == (6,) * 24
    assert detail.quality.same_weekday is True
    assert detail.quality.spread_percent == 0.0
    assert detail.kwh == dict.fromkeys(range(24), 1.0)


def test_a_young_installation_uses_every_day() -> None:
    days = [TARGET - timedelta(days=k) for k in range(1, 5)]
    detail = past._typical_detail(flows(days), TARGET, 6)
    assert detail.quality.same_weekday is False
    assert detail.quality.days_per_hour == (4,) * 24


def test_spread_of_the_days() -> None:
    assert spread_percent([10.0, 10.0]) is None  # trop peu de journées
    assert spread_percent([0.0, 0.0, 0.0]) is None
    assert spread_percent([8.0, 10.0, 12.0]) == 16.3


def state_with(
    days: int = 6,
    missing: int = 0,
    same: bool = True,
    spread: float | None = 10.0,
    fallback: bool = False,
    status: dict[str, str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    quality = BaselineQuality(
        days_per_hour=(0,) * missing + (days,) * (24 - missing),
        same_weekday=same,
        spread_percent=spread,
    )
    warnings = [{"code": "prevision_open_meteo", "params": {}}] if fallback else []
    return {STORED_KEY: stored(quality, warnings, status or {}), **extra}


def codes(found: Any) -> dict[str, str]:
    return {factor.code: factor.level for factor in found.factors}


def test_good_data_give_good_forecasts() -> None:
    found = assess(state_with(status={"Lave-linge": "ok"}), 0, solar=True)
    assert found is not None
    assert found.level == "good"
    assert found.score == 100
    assert codes(found) == {
        "consumption_history": "good",
        "consumption_regularity": "good",
        "solar_source": "good",
        "weather_horizon": "good",
        "cycle_profiles": "good",
    }


def test_hours_without_history_and_far_days_lower_the_quality() -> None:
    found = assess(state_with(missing=8, spread=45.0, fallback=True), 5, solar=True)
    assert found is not None
    assert found.level == "poor"
    assert codes(found)["consumption_history"] == "poor"
    assert codes(found)["consumption_regularity"] == "poor"
    assert codes(found)["solar_source"] == "fair"
    assert codes(found)["weather_horizon"] == "poor"
    # Les critères les plus faibles d'abord.
    assert found.factors[0].level == "poor"
    history = next(f for f in found.factors if f.code == "consumption_history")
    assert history.params["missing_hours"] == 8


def test_a_house_without_solar_is_judged_on_its_consumption() -> None:
    found = assess(state_with(), 3, solar=False)
    assert found is not None
    assert set(codes(found)) == {"consumption_history", "consumption_regularity"}


def test_missing_cycle_profiles_and_history_import() -> None:
    found = assess(
        state_with(
            status={"Lave-linge": "insuffisant", "Sèche-linge": "ok"}, historique_en_reprise=3
        ),
        0,
        solar=False,
    )
    assert found is not None
    assert codes(found)["cycle_profiles"] == "fair"
    assert codes(found)["history_import"] == "poor"
    assert found.level != "good"
    profiles = next(f for f in found.factors if f.code == "cycle_profiles")
    assert profiles.params == {"devices": "Lave-linge", "count": 1}


def test_a_plan_from_before_has_no_quality() -> None:
    assert assess({"date_cible": "2026-11-11"}, 0, solar=True) is None
