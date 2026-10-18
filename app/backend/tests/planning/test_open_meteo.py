"""Prévision Open-Meteo d'après les panneaux décrits (lot 4.4)."""

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.planning.test_assemble import Reader, StubClient
from tests.test_health import _settings
from wattslot import configuration, profiles
from wattslot.aggregation import HOUR
from wattslot.configuration import Automation, Behavior, Configuration, DeviceSettings
from wattslot.home_assistant import HomeAssistantClient
from wattslot.main import create_app
from wattslot.planning import open_meteo
from wattslot.planning.open_meteo import OpenMeteo, OpenMeteoUnavailable
from wattslot.planning.sources import Forecasts, ForecastUnavailable, PlanningSettings
from wattslot.solar_panels import PanelArray, SolarPanels
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore

PARIS = ZoneInfo("Europe/Paris")
TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
SOUTH = SolarPanels(arrays=[PanelArray(kwp=3)])


def response(gti: float = 500.0, temperature: float = 20.0, around: date = TODAY) -> dict[str, Any]:
    """Réponse au format d'Open-Meteo : 7 jours passés et 8 à venir au quart d'heure, irradiance
    ``gti`` de 12 h à 14 h (heure de Paris, quarts d'heure finissant à 12 h 15 … 14 h)."""
    start = datetime.combine(around - timedelta(days=7), time(), UTC)
    times, irradiance, temperatures = [], [], []
    for index in range(15 * 96):
        moment = start + timedelta(minutes=15 * index)
        begins = (moment - timedelta(minutes=15)).astimezone(PARIS)
        times.append(int(moment.timestamp()))
        irradiance.append(gti if 12 <= begins.hour < 14 else 0.0)
        temperatures.append(temperature)
    return {
        "minutely_15": {
            "time": times,
            "global_tilted_irradiance": irradiance,
            "temperature_2m": temperatures,
        }
    }


class Fake:
    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        self.answer = answer
        self.urls: list[str] = []

    async def __call__(self, url: str) -> dict[str, Any]:
        self.urls.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def source(
    tmp_path: Path, get: Fake, panels: SolarPanels = SOUTH, now: datetime = NOW
) -> OpenMeteo:
    return OpenMeteo(open_database(tmp_path), [panels], 45.764, 4.8357, get, lambda: now)


def test_power_follows_irradiance_and_cell_temperature() -> None:
    # 1 000 W/m², air à 25 °C : cellules à 59,2 °C, soit 13,7 % de perte.
    assert open_meteo.power_w(1000, 25, 3, 0.9) == pytest.approx(3000 * 0.8632 * 0.9)
    assert open_meteo.power_w(0, 10, 3, 0.9) == 0


def test_the_query_rounds_the_position_and_turns_the_azimuth() -> None:
    url = open_meteo.query(45.764, 4.8357, PanelArray(kwp=3, tilt=35, azimuth=90))
    assert "latitude=45.76&longitude=4.84" in url
    assert "tilt=35&azimuth=-90" in url  # est
    assert "past_days=7&forecast_days=8" in url


def test_hourly_energy_sums_the_arrays_under_the_inverter(tmp_path: Path) -> None:
    two = SolarPanels(arrays=[PanelArray(kwp=3), PanelArray(kwp=2, azimuth=270)], efficiency=1)
    found = asyncio.run(
        source(tmp_path, Fake(response(gti=500, temperature=0)), two).hourly(TODAY, PARIS)
    )

    # 500 W/m² à 0 °C : cellules à 17,1 °C, gain de 3,16 % ; 5 kWc.
    expected = 5 * 0.5 * (1 + 0.004 * (25 - 17.1))
    assert {h: kwh for h, kwh in found.items() if kwh} == pytest.approx(
        {12: expected, 13: expected}
    )

    capped = two.model_copy(update={"inverter_kw": 2.0})
    (tmp_path / "b").mkdir()
    found = asyncio.run(source(tmp_path / "b", Fake(response(500, 0)), capped).hourly(TODAY, PARIS))
    assert {h: kwh for h, kwh in found.items() if kwh} == pytest.approx({12: 2.0, 13: 2.0})


def test_responses_are_kept_an_hour_and_used_a_day_when_open_meteo_fails(tmp_path: Path) -> None:
    get = Fake(response())
    asyncio.run(source(tmp_path, get).hourly(TODAY, PARIS))
    asyncio.run(source(tmp_path, get, now=NOW + timedelta(minutes=50)).hourly(TODAY, PARIS))
    assert len(get.urls) == 1

    failing = Fake(OSError("réseau"))
    later = source(tmp_path, failing, now=NOW + timedelta(hours=5))
    assert asyncio.run(later.hourly(TODAY, PARIS))  # dernière réponse, vieille de 5 h
    assert len(failing.urls) == 1

    too_old = source(tmp_path, failing, now=NOW + timedelta(days=2))
    with pytest.raises(OpenMeteoUnavailable):
        asyncio.run(too_old.hourly(TODAY, PARIS))


def test_open_meteo_comes_after_the_energy_dashboard(tmp_path: Path) -> None:
    empty = cast(HomeAssistantClient, StubClient({"energy/solar_forecast": {}}))
    fallback = source(tmp_path, Fake(response()))

    hourly, warnings = asyncio.run(
        Forecasts(empty, PARIS, PlanningSettings(), fallback).hourly(TODAY)
    )
    assert {h for h, kwh in hourly.items() if kwh} == {12, 13}
    assert warnings == [{"code": "prevision_open_meteo", "params": {}}]

    with pytest.raises(ForecastUnavailable):  # sans panneaux, comme avant
        asyncio.run(Forecasts(empty, PARIS, PlanningSettings()).hourly(TODAY))
    with pytest.raises(ForecastUnavailable):  # au-delà des 8 jours d'Open-Meteo
        asyncio.run(
            Forecasts(empty, PARIS, PlanningSettings(), fallback).hourly(TODAY + timedelta(9))
        )


def test_fallback_needs_panels_on_a_planned_solar_installation_and_a_position(
    tmp_path: Path,
) -> None:
    database = open_database(tmp_path)
    located = cast(
        HomeAssistantClient,
        SimpleNamespace(snapshot=SimpleNamespace(config={"latitude": 45.7, "longitude": 4.8})),
    )
    nowhere = cast(HomeAssistantClient, SimpleNamespace(snapshot=SimpleNamespace(config={})))
    solar = DeviceSettings(
        key="solar", behavior=Behavior.PRODUCTION, automation=Automation.INFORM, panels=SOUTH
    )
    with_panels = Configuration(devices=[solar])

    assert open_meteo.fallback_for(database, with_panels, located) is not None
    assert open_meteo.fallback_for(database, with_panels, nowhere) is None
    assert open_meteo.fallback_for(database, Configuration(), located) is None
    unplanned = Configuration(devices=[solar.model_copy(update={"planned": False})])
    assert open_meteo.fallback_for(database, unplanned, located) is None


def test_panels_are_kept_in_the_configuration(tmp_path: Path) -> None:
    profile = profiles.load("reference")
    panels = SolarPanels(
        arrays=[PanelArray(kwp=3.2, tilt=20, azimuth=135), PanelArray(kwp=1.6, azimuth=225)],
        inverter_kw=4,
    )
    solar = next(d for d in profile.home.devices if d.kind.value == "SolarInstallation")
    settings = DeviceSettings(
        key=solar.key, behavior=Behavior.PRODUCTION, automation=Automation.INFORM, panels=panels
    )
    saved = profile.configuration.model_copy(
        update={"devices": [*profile.configuration.devices, settings]}
    )
    graph = GraphStore(tmp_path)
    configuration.save(graph, saved)

    found = configuration.load(graph).of(solar.key)
    assert found is not None and found.panels == panels
    assert configuration.validate(profile.home, saved) == []
    wrong = saved.model_copy(
        update={"devices": [d.model_copy(update={"panels": panels}) for d in saved.devices]}
    )
    assert "panels_not_used" in {i.code for i in configuration.validate(profile.home, wrong)}


def test_comparison_with_the_measured_production(tmp_path: Path) -> None:
    profile = profiles.load("reference")
    produced = [
        s.entity_id
        for d in profile.home.devices
        for s in d.sensors
        if s.role.value == "EnergyProduced"
    ]
    reader = Reader()
    yesterday = TODAY - timedelta(days=1)
    for hour in (12, 13):
        moment = datetime.combine(yesterday, time(hour), PARIS)
        reader.add(produced[0], HOUR, moment, energy_kwh=1.0)

    fallback = source(tmp_path, Fake(response(gti=500, temperature=25)), SOUTH)
    found = asyncio.run(open_meteo.compare(fallback, profile.home, reader, TODAY, PARIS))

    assert found.available and len(found.days) == 7 and found.days[-1].day == yesterday
    forecast = found.days[-1].forecast_kwh
    assert forecast == pytest.approx(2 * 3 * 0.5 * (1 - 0.004 * 0.0342 * 500) * 0.9, abs=0.01)
    assert found.days[-1].measured_kwh == 2.0
    assert found.days[0].measured_kwh is None
    assert found.ratio == pytest.approx(2.0 / forecast, abs=0.01)


def test_comparison_route_without_panels(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        found = api.get("/api/forecast/comparison").json()
    assert found == {"available": False, "reason": "no_panels", "days": [], "ratio": None}
