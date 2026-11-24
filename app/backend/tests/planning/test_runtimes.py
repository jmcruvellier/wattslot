"""Durées de fonctionnement à placer (lot 3.4) : réglages, calcul, données réelles, dashboard."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

from tests.planning.test_assemble import MODEL, Reader
from tests.planning.test_configured_run import plans
from tests.v1_oracle import STATES, load, state_named
from wattslot import configuration
from wattslot.aggregation import QUARTER
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_assistant import HomeAssistantClient
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.languages import LANGUAGES
from wattslot.planning.actual import runtime_segments, speed_thresholds
from wattslot.planning.assemble import configured, measured_speeds, southern
from wattslot.planning.engine import Result, plan_day
from wattslot.planning.explain import render
from wattslot.planning.horizon import DayForecast, next_day_input
from wattslot.planning.inputs import V1_POOL, PlanningInput, Runtime, from_v1
from wattslot.planning.plan import POOL
from wattslot.planning.problem import from_input
from wattslot.runtime_settings import RuntimeSettings, Speed, problems, season
from wattslot.storage.graph import GraphStore

PARIS = ZoneInfo("Europe/Paris")
DEHUMIDIFIER = HomeDevice(
    key="dehumidifier",
    kind=DeviceKind.OTHER_LOAD,
    name="Déshumidificateur",
    sensors=[HomeSensor(entity_id="sensor.dehum_power", role=Role.POWER_CONSUMED)],
)
DRYING = RuntimeSettings(
    speeds=[Speed(name="normal", kw=0.3)],
    minimum_hours={"summer": 3, "mid_season": 3, "winter": 3},
    max_starts=3,
)


def test_seasons_in_both_hemispheres() -> None:
    assert season(date(2026, 7, 1)) == "summer" and season(date(2026, 7, 1), True) == "winter"
    assert season(date(2026, 1, 1), True) == "summer"
    assert season(date(2026, 4, 15)) == "mid_season" == season(date(2026, 10, 15), True)


def test_problems_and_saved_settings(tmp_path: Path) -> None:
    assert problems(RuntimeSettings()) == [] and problems(DRYING) == []
    bad = RuntimeSettings(
        speeds=[Speed(name="off", kw=1)], minimum_hours={"spring": 2, "summer": 30}
    )
    assert [code for code, _ in problems(bad)] == [
        "runtime_speed_names",
        "runtime_seasons",
        "runtime_too_long",
    ]
    graph = GraphStore(tmp_path)
    saved = Configuration(
        devices=[DeviceSettings(key="dehumidifier", behavior=Behavior.RUNTIME, runtime=DRYING)]
    )
    configuration.save(graph, saved)
    assert configuration.load(graph) == saved
    misplaced = Configuration(
        devices=[DeviceSettings(key="dehumidifier", behavior=Behavior.CYCLE, runtime=DRYING)]
    )
    home = HomeModel(devices=[DEHUMIDIFIER])
    assert [i.code for i in configuration.validate(home, misplaced)] == ["runtime_not_used"]


def test_two_runtimes_in_the_same_day() -> None:
    state, _ = load(STATES[0])
    dryer = Runtime(
        name="Déshumidificateur",
        speeds=(("normal", 0.3),),
        minimum_hours=dict(DRYING.minimum_hours),
        skip_days={},
        max_starts=3,
    )
    data = replace(from_v1(state), runtimes=(V1_POOL, dryer))

    result = plan_day(from_input(data))

    by_name = {r.device: r for r in result.day.runtimes}
    assert set(by_name) == {POOL, "Déshumidificateur"}
    hours = sum(
        s.end_hour - s.start_hour for s in by_name["Déshumidificateur"].segments if s.mode != "off"
    )
    assert hours >= 3  # durée minimale tenue
    assert result.plan.runtimes["Déshumidificateur"]


def test_forced_minimum_uses_the_lowest_speed_only() -> None:
    state, _ = load(STATES[0])
    problem = from_input(from_v1(state))
    forced = replace(problem.runtimes[0], minimum_forced=True, min_hours=2)
    result_plan = plan_day(replace(problem, runtimes=[forced])).plan
    modes = set(result_plan.runtimes[POOL].values())
    assert modes <= {"off", "silence"}
    assert list(result_plan.runtimes[POOL].values()).count("silence") == 2


def _sunny(hours: int) -> PlanningInput:
    """Journée ensoleillée de la mi-saison (calcul à minuit), filtration réglée sur ``hours``."""
    state, _ = load(state_named("synthetic_sunny"))
    data = from_v1(state)
    assert season(data.day, data.southern) == "mid_season"
    pool = replace(V1_POOL, minimum_hours={**V1_POOL.minimum_hours, "mid_season": hours})
    return replace(data, runtimes=(pool,))


def _running(result: Result, name: str = POOL) -> list[int]:
    return [hour for hour, mode in result.plan.runtimes[name].items() if mode != "off"]


def test_a_season_set_to_zero_places_no_hour_even_with_surplus() -> None:
    """Saison réglée sur 0 h : aucune heure, même quand le surplus solaire serait injecté
    (constaté le 23/11/2026 : 1 h placée en hiver, « rien l'hiver » à l'écran)."""
    problem = from_input(_sunny(0))
    assert problem.runtimes[0].off_season and problem.runtimes[0].min_hours == 0

    result = plan_day(problem)

    assert _running(result) == []
    (pool,) = result.day.runtimes
    assert [s.mode for s in pool.segments] == ["off"]
    assert pool.explanation is not None
    assert [r.code for r in pool.explanation.reasons][1:] == ["runtime_off", "season_off"]
    for lang in LANGUAGES:
        assert "0" in render(pool.explanation, lang)
    # Sans cette règle, le même jour absorbe le surplus : c'est elle qui retient la pompe.
    free = replace(problem, runtimes=[replace(problem.runtimes[0], off_season=False)])
    assert len(_running(plan_day(free))) > 1


def test_a_season_with_a_minimum_still_runs_longer_on_surplus() -> None:
    for minimum in (1, 2):  # mi-saison et été de la filtration de référence
        problem = from_input(_sunny(minimum))
        assert not problem.runtimes[0].off_season and problem.runtimes[0].min_hours == minimum

        assert len(_running(plan_day(problem))) > minimum  # minimum tenu, surplus absorbé


def test_a_minimum_already_done_is_not_a_season_set_to_zero() -> None:
    state, _ = load(state_named("synthetic_realignment"))
    problem = from_input(from_v1(state))  # 13 h : l'heure de la mi-saison est déjà faite
    assert problem.runtimes[0].min_hours == 0 and not problem.runtimes[0].off_season

    assert _running(plan_day(problem))  # le surplus de l'après-midi reste absorbé


def test_a_season_set_to_zero_holds_for_the_next_days_too() -> None:
    data = _sunny(0)
    forecast = DayForecast(net_kwh=dict(data.net_kwh), production_kwh=dict(data.production_kwh))
    following = next_day_input(data, data.day + timedelta(days=1), forecast, 1.0)

    assert _running(plan_day(from_input(following))) == []


def test_configured_runtimes_with_a_measured_speed() -> None:
    state, _ = load(STATES[0])
    data = from_v1(state)
    home = HomeModel(devices=[*MODEL.devices, DEHUMIDIFIER])
    settings = Configuration(
        devices=[DeviceSettings(key="dehumidifier", behavior=Behavior.RUNTIME)]
    )

    found = configured(data, home, settings, {"dehumidifier": 0.28}).runtimes

    assert [(r.name, r.speeds) for r in found] == [("Déshumidificateur", (("normal", 0.28),))]
    assert configured(data, home, settings).runtimes[0].speeds == (("normal", 0.5),)


def test_measured_speed_is_the_median_running_power() -> None:
    reader = Reader()
    today = date(2026, 10, 16)
    start = datetime(2026, 10, 10, 10, tzinfo=PARIS)
    for k, watts in enumerate([2.0, 260.0, 300.0, 310.0, 5.0]):  # veille ignorée
        reader.add("sensor.dehum_power", QUARTER, start + timedelta(minutes=15 * k), mean=watts)
    home = HomeModel(devices=[DEHUMIDIFIER])
    settings = Configuration(
        devices=[DeviceSettings(key="dehumidifier", behavior=Behavior.RUNTIME)]
    )

    assert measured_speeds(home, settings, reader, today, PARIS) == {"dehumidifier": 0.3}


def test_southern_hemisphere_from_home_assistant() -> None:
    def client(latitude: object) -> HomeAssistantClient:
        snapshot = SimpleNamespace(config={"latitude": latitude})
        return cast(HomeAssistantClient, SimpleNamespace(snapshot=snapshot))

    assert southern(client(-33.9)) and not southern(client(48.8)) and not southern(client(None))


def test_real_modes_from_the_power_of_each_speed() -> None:
    thresholds = speed_thresholds([("high", 1.0), ("low", 0.2), ("mid", 0.6)], on_w=20)
    assert thresholds == [("low", 20), ("mid", 400.0), ("high", 800.0)]
    start = datetime(2026, 10, 16, 8, tzinfo=UTC)
    power = [(start + timedelta(hours=h), w) for h, w in enumerate([300, 700, 900, 0])]

    found = runtime_segments(power, None, PARIS, thresholds)

    assert [s["mode"] for s in found] == ["low", "mid", "high"]


def test_a_home_with_a_dehumidifier_plans_it(tmp_path: Path) -> None:
    home = HomeModel(devices=[*MODEL.devices, DEHUMIDIFIER])
    settings = Configuration(
        devices=[DeviceSettings(key="dehumidifier", behavior=Behavior.RUNTIME, runtime=DRYING)]
    )

    for plan in plans(tmp_path, home, settings):
        assert [r.device for r in plan.runtimes] == ["Déshumidificateur"]
