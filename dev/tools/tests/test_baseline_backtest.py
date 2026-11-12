"""Rejeu de la consommation de base sur l'historique (``baseline_backtest.py``).

cd dev && python -m pytest tools/tests
"""

import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from tools import baseline_backtest as backtest
from wattslot.planning import past

START = date(2024, 1, 1)
DAYS = 800


def flows(level: Callable[[date], float], days: int = DAYS) -> past._Flows:
    """Maison sans solaire ni batterie : ``level(jour)`` kWh soutirés par heure."""
    imported = {
        START + timedelta(days=k): dict.fromkeys(range(24), level(START + timedelta(days=k)))
        for k in range(days)
    }
    return past._Flows(
        produced={},
        imported=imported,
        exported={},
        charged={},
        discharged={},
        appliances={},
        has_battery=False,
    )


def seasonal(day: date) -> float:
    """Consommation qui suit la saison, identique d'une année à l'autre (52 semaines)."""
    return 1.0 + 0.5 * math.cos(2 * math.pi * (day - START).days / backtest.YEAR_DAYS)


def test_recent_days_match_the_application() -> None:
    found = flows(lambda day: 1.0 + (day - START).days % 11 / 10, days=120)
    bases = backtest.day_bases(found)
    target = START + timedelta(days=100)
    recent = backtest.recent_days(bases, target)
    assert recent is not None and len(recent) == backtest.OCCURRENCES
    window = backtest.restrict(found, target - timedelta(days=backtest.WINDOW_DAYS), target)
    expected = past._typical_detail(window, target, backtest.OCCURRENCES).kwh
    assert backtest.mean_profile(bases, recent) == pytest.approx(expected)


def test_restrict_hides_the_target_and_what_follows() -> None:
    target = START + timedelta(days=100)
    window = backtest.restrict(flows(seasonal, days=120), target - timedelta(days=7), target)
    assert sorted(window.imported) == [target - timedelta(days=k) for k in range(7, 0, -1)]


def test_constant_house_has_no_error() -> None:
    result = backtest.replay(flows(lambda day: 0.4))
    assert result.days > 300
    for name in (backtest.YEARS, backtest.TREND):
        score = result.overall[name]
        assert score.days > 300
        assert score.hourly == pytest.approx(0.0, abs=1e-9)
        assert score.hourly_current == pytest.approx(0.0, abs=1e-9)
    assert backtest.TEMPERATURE not in result.overall  # aucune température donnée


def test_trend_follows_a_season_repeated_each_year() -> None:
    result = backtest.replay(flows(seasonal))
    trend = result.overall[backtest.TREND]
    assert trend.hourly < trend.hourly_current / 2
    assert trend.better > trend.days / 2
    assert set(result.monthly[backtest.TREND]) >= {"2025-03", "2025-10"}


def test_past_years_need_a_year_of_history() -> None:
    result = backtest.replay(flows(seasonal, days=300))
    assert result.days > 200
    assert backtest.YEARS not in result.overall
    assert backtest.TREND not in result.overall
    assert "pas de données" in backtest.report(result)


def test_temperature_explains_a_heated_house() -> None:
    def outside(day: date) -> float:
        return 10.0 + 8.0 * math.sin((day - START).days / 9)

    temperatures = {
        START + timedelta(days=k): outside(START + timedelta(days=k)) for k in range(200)
    }
    result = backtest.replay(flows(lambda day: 2.0 - outside(day) / 20, days=200), temperatures)
    score = result.overall[backtest.TEMPERATURE]
    assert score.hourly == pytest.approx(0.0, abs=1e-6)
    assert score.hourly_current > 0.01 * score.measured


def test_ratio_is_bounded() -> None:
    assert backtest.scaled({0: 1.0}, 10.0) == {0: backtest.RATIO_LIMITS[1]}
    assert backtest.scaled({0: 1.0}, 0.01) == {0: backtest.RATIO_LIMITS[0]}


def test_incomplete_day_is_not_replayed() -> None:
    found = flows(lambda day: 0.4, days=120)
    target = START + timedelta(days=100)
    del found.imported[target][3]
    result = backtest.replay(found)
    assert target.isoformat() not in {row["jour"] for row in result.rows}


def test_reader_reads_by_chunks() -> None:
    urls: list[str] = []

    def fetch(url: str) -> Any:
        urls.append(url)
        return [
            {
                "entity_id": "sensor.grid",
                "period": "PT1H",
                "start": "2025-01-01T00:00:00Z",
                "energy_kwh": 0.5,
            }
        ]

    reader = backtest.ApiReader("http://192.0.2.10:8000/", fetch)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    found = reader.read("sensor.grid", "PT1H", start, start + timedelta(days=200))
    assert len(urls) == 3 and len(found) == 3
    assert urls[0].startswith("http://192.0.2.10:8000/api/aggregates?entity_id=sensor.grid")
    assert found[0].energy_kwh == 0.5


def test_temperatures_skip_missing_days() -> None:
    payload = {"daily": {"time": ["2025-01-01", "2025-01-02"], "temperature_2m_mean": [3.5, None]}}
    assert backtest.temperatures_from(payload) == {date(2025, 1, 1): 3.5}
