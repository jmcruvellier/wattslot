"""Précision des plages tarifaires, sans modifier la maille horaire du moteur."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_configuration import HOME
from tests.test_health import _settings
from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.home_model import vocab
from wattslot.main import create_app
from wattslot.storage.graph import GraphStore
from wattslot.tariff import PriceBand, Tariff, TariffKind, off_peak_ranges, problems

DAY = date(2026, 10, 16)


def tariff_with(*bands: PriceBand, base: float = 0.30) -> Tariff:
    return Tariff(kind=TariffKind.TIME_OF_USE, base_eur_kwh=base, bands=list(bands))


def test_uniform_price_stays_exact_across_several_bands() -> None:
    tariff = tariff_with(
        PriceBand(start_hour=1, end_hour=1, end_minute=17, eur_kwh=0.12),
        PriceBand(start_hour=1, start_minute=17, end_hour=2, eur_kwh=0.12),
    )
    assert tariff.hourly(DAY)[1] == 0.12
    assert tariff.hourly(DAY)[0] == 0.30


def test_mixed_hour_rounds_to_six_decimals_but_uniform_hour_is_exact() -> None:
    tariff = tariff_with(
        PriceBand(start_hour=1, end_hour=2, end_minute=1, eur_kwh=0.123456789),
    )
    assert tariff.hourly(DAY)[1] == 0.123456789
    assert tariff.hourly(DAY)[2] == 0.297058


def test_two_bands_in_one_hour_and_first_overlap_wins() -> None:
    first = PriceBand(start_hour=1, start_minute=10, end_hour=1, end_minute=40, eur_kwh=0.12)
    second = PriceBand(start_hour=1, start_minute=30, end_hour=2, eur_kwh=0.18)
    assert tariff_with(first, second).hourly(DAY)[1] == 0.17
    assert tariff_with(second, first).hourly(DAY)[1] == 0.18


def test_identical_compositions_have_exactly_equal_prices() -> None:
    tariff = tariff_with(
        PriceBand(start_hour=1, end_hour=1, end_minute=20, eur_kwh=0.12),
        PriceBand(start_hour=1, start_minute=20, end_hour=1, end_minute=40, eur_kwh=0.18),
        PriceBand(start_hour=2, start_minute=20, end_hour=2, end_minute=40, eur_kwh=0.12),
        PriceBand(start_hour=2, start_minute=40, end_hour=3, eur_kwh=0.18),
    )
    assert tariff.hourly(DAY)[1] == tariff.hourly(DAY)[2] == 0.20


def test_equal_full_price_is_not_a_false_off_peak() -> None:
    tariff = tariff_with(
        PriceBand(start_hour=1, start_minute=17, end_hour=2, end_minute=41, eur_kwh=0.12),
        base=0.12,
    )
    assert set(tariff.hourly(DAY).values()) == {0.12}
    assert off_peak_ranges(tariff, DAY) == []


@pytest.mark.parametrize(
    ("start", "end", "empty"),
    [(0, 0, True), (15, 15, True), (15, 38, False), (38, 15, False)],
)
def test_band_empty_compares_minutes(start: int, end: int, empty: bool) -> None:
    tariff = tariff_with(
        PriceBand(start_hour=0, start_minute=start, end_hour=0, end_minute=end, eur_kwh=0.12)
    )
    assert ("band_empty" in [code for code, _ in problems(tariff)]) is empty


def test_band_ending_at_midnight_does_not_include_next_day() -> None:
    tariff = tariff_with(PriceBand(start_hour=22, start_minute=30, end_hour=0, eur_kwh=0.12))
    assert tariff.hourly(DAY)[0] == 0.30
    assert tariff.hourly(DAY)[22] == 0.21
    assert tariff.hourly(DAY)[23] == 0.12
    assert problems(tariff) == []


def test_month_filter_applies_after_midnight_to_current_month() -> None:
    tariff = tariff_with(
        PriceBand(start_hour=22, end_hour=0, end_minute=30, eur_kwh=0.12, months=[10])
    )
    assert tariff.hourly(date(2026, 10, 1))[0] == 0.21
    assert tariff.hourly(date(2026, 11, 1))[0] == 0.30


def test_wrapping_within_same_hour_covers_both_sides() -> None:
    tariff = tariff_with(
        PriceBand(start_hour=1, start_minute=40, end_hour=1, end_minute=10, eur_kwh=0.12)
    )
    assert tariff.hourly(DAY)[0] == tariff.hourly(DAY)[2] == 0.12
    assert tariff.hourly(DAY)[1] == 0.21


def test_legacy_graph_really_has_no_minute_predicates(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    legacy = tariff_with(PriceBand(start_hour=1, end_hour=6, eur_kwh=0.12))
    configuration.save(graph, Configuration(tariff=legacy))
    # Supprimer réellement les prédicats : ne pas seulement sérialiser des minutes nulles.
    for predicate in ("startMinute", "endMinute"):
        graph.update(f"DELETE WHERE {{ GRAPH ?g {{ ?s <{vocab(predicate).value}> ?v }} }}")
        assert (
            list(
                graph.select(
                    f"SELECT ?s WHERE {{ GRAPH ?g {{ ?s <{vocab(predicate).value}> ?v }} }}"
                )
            )
            == []
        )
    restored = configuration.load(graph).tariff
    assert restored == legacy
    assert restored is not None
    assert restored.bands[0].start_minute == restored.bands[0].end_minute == 0
    assert restored.hourly(DAY)[1] == 0.12


def test_api_round_trip_and_legacy_payload(tmp_path: Path) -> None:
    tariff = tariff_with(
        PriceBand(start_hour=22, start_minute=30, end_hour=0, end_minute=38, eur_kwh=0.12)
    )
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.put("/api/home", json=HOME.model_dump(mode="json")).status_code == 200
        body = {"devices": [], "tariff": tariff.model_dump(mode="json")}
        saved = api.put("/api/configuration", json=body)
        assert saved.status_code == 200
        assert saved.json()["tariff"] == body["tariff"]
        assert api.get("/api/configuration").json()["tariff"] == body["tariff"]
        legacy = {
            "kind": "TimeOfUseTariff",
            "base_eur_kwh": 0.30,
            "bands": [{"start_hour": 1, "end_hour": 6, "eur_kwh": 0.12}],
        }
        saved = api.put("/api/configuration", json={"devices": [], "tariff": legacy})
        assert saved.status_code == 200
        assert saved.json()["tariff"]["bands"][0]["start_minute"] == 0
        invalid = tariff.model_dump(mode="json")
        invalid["bands"][0].update(end_hour=24, end_minute=1)
        assert (
            api.put("/api/configuration", json={"devices": [], "tariff": invalid}).status_code
            == 422
        )
