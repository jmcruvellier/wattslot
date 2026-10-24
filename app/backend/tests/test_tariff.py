"""Tarif générique (lot 3.2) : prix horaires, anomalies, enregistrement, prix vus par le calcul."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_configuration import HOME
from tests.test_health import _settings
from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.main import create_app
from wattslot.planning.horizon import DayForecast, next_day_input
from wattslot.planning.inputs import from_v1
from wattslot.planning.problem import from_input
from wattslot.storage.graph import GraphStore
from wattslot.tariff import DEFAULT, V1, PriceBand, Tariff, TariffKind, problems

FRIDAY, SATURDAY, JULY_DAY = date(2026, 10, 16), date(2026, 10, 17), date(2026, 7, 15)


def test_minute_bands_are_weighted_without_rounding() -> None:
    tariff = Tariff(
        kind=TariffKind.TIME_OF_USE,
        base_eur_kwh=0.30,
        bands=[PriceBand(start_hour=1, start_minute=30, end_hour=5, end_minute=38, eur_kwh=0.12)],
    )

    prices = tariff.hourly(FRIDAY)

    assert prices[0] == 0.30
    assert prices[1] == pytest.approx((30 * 0.30 + 30 * 0.12) / 60)
    assert [prices[h] for h in (2, 3, 4)] == [0.12] * 3
    assert prices[5] == pytest.approx((38 * 0.12 + 22 * 0.30) / 60, abs=1e-15)
    assert prices[6] == 0.30


WEEKEND = Tariff(
    kind=TariffKind.TIME_OF_USE,
    base_eur_kwh=0.30,
    bands=[
        PriceBand(start_hour=0, end_hour=24, eur_kwh=0.10, weekdays=[5, 6]),  # week-end creux
        PriceBand(start_hour=1, end_hour=7, eur_kwh=0.20),
        PriceBand(start_hour=12, end_hour=14, eur_kwh=0.05, months=[6, 7, 8]),
    ],
    export_eur_kwh=0.06,
)


def test_midnight_bands_use_civil_day_filters() -> None:
    band = PriceBand(
        start_hour=22,
        start_minute=30,
        end_hour=0,
        end_minute=38,
        eur_kwh=0.12,
        weekdays=[4],
        months=[10],
    )
    tariff = Tariff(kind=TariffKind.TIME_OF_USE, base_eur_kwh=0.30, bands=[band])
    assert problems(tariff) == []
    assert tariff.hourly(FRIDAY)[0] == 0.186
    assert tariff.hourly(FRIDAY)[22] == 0.21
    assert tariff.hourly(FRIDAY)[23] == 0.12
    assert set(tariff.hourly(SATURDAY).values()) == {0.30}
    assert not band.applies(JULY_DAY, 23)
    assert band.applies(FRIDAY, 0, 37)
    assert not band.applies(FRIDAY, 0, 38)


def test_hourly_prices() -> None:
    assert DEFAULT.hourly(FRIDAY) == dict.fromkeys(range(24), 0.25)
    friday = WEEKEND.hourly(FRIDAY)
    assert friday[0] == 0.30 and friday[1] == 0.20 and friday[6] == 0.20 and friday[7] == 0.30
    assert friday[12] == 0.30  # plage d'été seulement
    assert set(WEEKEND.hourly(SATURDAY).values()) == {0.10}  # la première plage l'emporte
    assert WEEKEND.hourly(JULY_DAY)[12] == 0.05
    v1 = V1.hourly(FRIDAY)
    assert [h for h in range(24) if v1[h] == 0.21] == [0, 1, 2, 3, 4, 5, 22, 23]


@pytest.mark.parametrize(
    "update",
    [
        {"start_minute": -1},
        {"start_minute": 60},
        {"end_minute": -1},
        {"end_minute": 60},
        {"end_hour": -1},
        {"end_hour": 25},
        {"end_hour": 24, "end_minute": 1},
    ],
)
def test_price_band_rejects_invalid_bounds(update: dict[str, int]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PriceBand.model_validate({"start_hour": 1, "end_hour": 2, "eur_kwh": 0.12, **update})


def test_problems() -> None:
    assert problems(V1) == [] and problems(WEEKEND) == []
    assert problems(Tariff(kind=TariffKind.TIME_OF_USE, base_eur_kwh=0.2)) == [
        ("tariff_without_bands", {})
    ]
    odd = Tariff(
        kind=TariffKind.SINGLE,
        base_eur_kwh=0.2,
        bands=[PriceBand(start_hour=8, end_hour=8, eur_kwh=0.1, weekdays=[7], months=[0])],
    )
    assert [code for code, _ in problems(odd)] == [
        "bands_not_used",
        "band_empty",
        "band_weekday",
        "band_month",
    ]


def test_minute_bands_round_trip_in_graph(tmp_path: Path) -> None:
    from wattslot.tariff import ColorPrices

    bands = [PriceBand(start_hour=1, start_minute=30, end_hour=5, end_minute=38, eur_kwh=0.12)]
    graph = GraphStore(tmp_path)
    tariffs = [
        Tariff(kind=TariffKind.TIME_OF_USE, base_eur_kwh=0.30, bands=bands),
        Tariff(
            kind=TariffKind.DAY_COLOR,
            base_eur_kwh=0.30,
            color_entity="sensor.color",
            colors=[ColorPrices(color="Bleu", base_eur_kwh=0.30, bands=bands)],
        ),
    ]
    for tariff in tariffs:
        configuration.save(graph, Configuration(tariff=tariff))
        restored = configuration.load(graph).tariff
        assert restored == tariff
        assert restored is not None
        assert restored.hourly(FRIDAY) == tariff.hourly(FRIDAY)


def test_saved_and_read_back_with_the_configuration(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    configuration.save(graph, Configuration(tariff=WEEKEND))

    assert configuration.load(graph).tariff == WEEKEND
    assert configuration.tariff_of(configuration.load(graph)) == WEEKEND
    configuration.save(graph, Configuration())
    assert configuration.tariff_of(configuration.load(graph)) == DEFAULT


def test_tariff_api(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        api.put("/api/home", json=HOME.model_dump(mode="json"))
        body = {"devices": [], "tariff": WEEKEND.model_dump(mode="json")}
        saved = api.put("/api/configuration", json=body).json()
        assert saved["tariff"] == WEEKEND.model_dump(mode="json")

        bad = {"devices": [], "tariff": {"kind": "TimeOfUseTariff", "base_eur_kwh": 0.2}}
        refused = api.put("/api/configuration", json=bad)
        assert refused.status_code == 422
        assert refused.json()["detail"][0]["code"] == "tariff_without_bands"


def test_the_calculation_sees_the_prices_of_each_day() -> None:
    state, _ = load(STATES[0])
    data = from_v1(state)
    assert from_input(data).prices_eur_kwh == V1.hourly(data.day)  # entrée de la v1

    configured = replace(data, tariff=WEEKEND)
    problem = from_input(configured)
    assert problem.prices_eur_kwh == WEEKEND.hourly(data.day)
    assert set(problem.export_prices_eur_kwh.values()) == {0.06}

    forecast = DayForecast(net_kwh={}, production_kwh={})
    saturday = next_day_input(configured, SATURDAY, forecast, 1.0)
    assert from_input(saturday).prices_eur_kwh == dict.fromkeys(range(24), 0.10)


def test_off_peak_ranges_for_the_dashboard() -> None:
    from wattslot.tariff import off_peak_ranges

    assert off_peak_ranges(V1, FRIDAY) == [(0, 6), (22, 24)]
    assert off_peak_ranges(DEFAULT, FRIDAY) == []
    assert off_peak_ranges(WEEKEND, FRIDAY) == [(1, 7)]
    assert off_peak_ranges(WEEKEND, SATURDAY) == []  # même prix toute la journée


CONTRACT = WEEKEND.model_copy(update={"subscription_eur_month": 15.5, "contract_kva": 9.0})


def test_the_contract_is_saved_and_read_back(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    configuration.save(graph, Configuration(tariff=CONTRACT))

    assert configuration.load(graph).tariff == CONTRACT
    configuration.save(graph, Configuration(tariff=WEEKEND))
    assert configuration.load(graph).tariff == WEEKEND  # sans contrat : 0 €, puissance inconnue


def test_the_subscription_of_a_day_follows_the_length_of_the_month() -> None:
    assert CONTRACT.subscription_eur(FRIDAY) == 0.5  # 31 jours en octobre
    assert CONTRACT.subscription_eur(date(2028, 2, 10)) == 15.5 / 29
    assert WEEKEND.subscription_eur(FRIDAY) == 0.0


def test_the_calculation_sees_the_contract() -> None:
    state, _ = load(STATES[0])
    problem = from_input(replace(from_v1(state), tariff=CONTRACT))

    assert problem.contract_kwh == 9.0
    assert problem.subscription_eur == CONTRACT.subscription_eur(problem.day)
    assert from_input(from_v1(state)).contract_kwh is None
