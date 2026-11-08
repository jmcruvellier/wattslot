"""Jours fériés comptés comme un dimanche dans les filtres des plages (week-end EDF, 2.0TD…)."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.main import create_app
from wattslot.storage.graph import GraphStore
from wattslot.tariff import (
    ColorPrices,
    Holidays,
    PriceBand,
    Tariff,
    TariffContext,
    TariffKind,
    holiday_choices,
    problems,
)

ARMISTICE = date(2026, 11, 11)  # mercredi férié en France
THURSDAY = date(2026, 11, 12)
GOOD_FRIDAY = date(2026, 4, 3)  # férié en Moselle et en Alsace, pas ailleurs en France

# Week-end + mercredi : prix réduit toute la journée ; le reste de la semaine, heures creuses.
WEEKEND = Tariff(
    kind=TariffKind.TIME_OF_USE,
    base_eur_kwh=0.25,
    bands=[
        PriceBand(start_hour=0, end_hour=24, eur_kwh=0.15, weekdays=[2, 5, 6]),
        PriceBand(start_hour=0, end_hour=6, eur_kwh=0.20),
    ],
    holidays=Holidays(country="FR"),
)


def test_a_holiday_counts_as_a_sunday() -> None:
    sunday_only = WEEKEND.model_copy(
        update={"bands": [PriceBand(start_hour=0, end_hour=24, eur_kwh=0.15, weekdays=[6])]}
    )
    assert sunday_only.hourly(ARMISTICE) == dict.fromkeys(range(24), 0.15)
    assert sunday_only.hourly(THURSDAY) == dict.fromkeys(range(24), 0.25)
    plain = sunday_only.model_copy(update={"holidays": None})
    assert plain.hourly(ARMISTICE) == dict.fromkeys(range(24), 0.25)


def test_the_weekday_bands_keep_their_order() -> None:
    assert WEEKEND.hourly(THURSDAY)[3] == 0.20
    assert WEEKEND.hourly(THURSDAY)[12] == 0.25
    assert WEEKEND.hourly(date(2026, 11, 14))[12] == 0.15  # samedi


def test_a_region_has_its_own_holidays() -> None:
    sunday = [PriceBand(start_hour=0, end_hour=24, eur_kwh=0.15, weekdays=[6])]
    france = Tariff(
        kind=TariffKind.TIME_OF_USE,
        base_eur_kwh=0.25,
        bands=sunday,
        holidays=Holidays(country="FR"),
    )
    moselle = france.model_copy(update={"holidays": Holidays(country="FR", subdivision="57")})
    assert france.hourly(GOOD_FRIDAY)[12] == 0.25
    assert moselle.hourly(GOOD_FRIDAY)[12] == 0.15


def test_day_color_bands_see_holidays_too() -> None:
    tariff = Tariff(
        kind=TariffKind.DAY_COLOR,
        base_eur_kwh=0.2,
        color_entity="sensor.color",
        colors=[
            ColorPrices(
                color="Bleu",
                base_eur_kwh=0.18,
                bands=[PriceBand(start_hour=0, end_hour=24, eur_kwh=0.12, weekdays=[6])],
            )
        ],
        holidays=Holidays(country="FR"),
    )
    context = TariffContext(colors={ARMISTICE: "Bleu", THURSDAY: "Bleu"})
    assert tariff.hourly(ARMISTICE, context)[12] == 0.12
    assert tariff.hourly(THURSDAY, context)[12] == 0.18


def test_an_unknown_country_is_a_problem_and_gives_no_holiday() -> None:
    unknown = WEEKEND.model_copy(update={"holidays": Holidays(country="ZZ")})
    assert ("holiday_country_unknown", {}) in problems(unknown)
    region = WEEKEND.model_copy(update={"holidays": Holidays(country="FR", subdivision="ZZ")})
    assert ("holiday_country_unknown", {}) in problems(region)
    assert ("holiday_country_unknown", {}) not in problems(WEEKEND)
    sunday = [PriceBand(start_hour=0, end_hour=24, eur_kwh=0.15, weekdays=[6])]
    assert unknown.model_copy(update={"bands": sunday}).hourly(ARMISTICE)[12] == 0.25


def test_saved_and_read_back(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    moselle = WEEKEND.model_copy(update={"holidays": Holidays(country="FR", subdivision="57")})
    for tariff in (WEEKEND, moselle, WEEKEND.model_copy(update={"holidays": None})):
        configuration.save(graph, Configuration(tariff=tariff))
        assert configuration.load(graph).tariff == tariff


def test_holiday_choices() -> None:
    found = holiday_choices(None, "FR")
    assert found.default_country == "FR" and found.country == "FR"
    assert {"FR", "ES", "IT", "DE"} <= set(found.countries)
    names = {r.code: r.name for r in found.subdivisions}
    assert names["57"] == "Moselle" and names["6AE"] == "Alsace"
    assert holiday_choices("ES", "FR").country == "ES"
    assert holiday_choices("ZZ", None).country is None
    assert holiday_choices(None, None).subdivisions == []


def test_holidays_route(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        found = api.get("/api/configuration/holidays", params={"country": "IT"}).json()
    assert found["country"] == "IT" and found["default_country"] is None
    assert "FR" in found["countries"]
