"""Profils de test (lot 3.8) et leurs états : chaque profil, chargé par l'import, calcule un plan
expliqué dont les contraintes tiennent, avec ses indicateurs, et un horizon de 7 jours dans le
budget de temps (10,8 s, mesuré sur le N150 avec la v1)."""

import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.v1_oracle import STATES, load
from wattslot import exchange, profiles
from wattslot.main import create_app
from wattslot.planning.assemble import configured
from wattslot.planning.engine import plan_day
from wattslot.planning.horizon import DayForecast, next_day_input
from wattslot.planning.inputs import CycleProfile, PlanningInput, TaskRequest, from_v1
from wattslot.planning.plan import Plan, RuntimePlan, Slot
from wattslot.planning.problem import Problem, from_input
from wattslot.tariff import TariffContext

TESTED = [
    "no_battery",
    "no_pool",
    "tempo",
    "dynamic",
    "ev",
    "two_dishwashers",
    "southern",
    "heat_pump",
]
BUDGET_S = 10.8


def base() -> PlanningInput:
    """Journée ensoleillée : chauffe-eau dû, lave-linge puis sèche-linge à placer."""
    state, _ = load(STATES[11])
    return from_v1(state)


def state_of(name: str) -> PlanningInput:
    """État de test du profil : l'état de base adapté à ce que le profil change."""
    profile = profiles.load(name)
    data = base()
    day = data.day
    if name == "no_battery":
        data = replace(data, battery=replace(data.battery, capacity_kwh=0, stored_kwh=0))
    if name == "tempo":
        data = replace(data, tariff_context=TariffContext(colors={day: "Rouge"}))
    if name == "dynamic":
        # Prix déjà en €/kWh : le facteur de l'entité (€/MWh) s'applique à la lecture dans HA.
        prices = {h: (0.05 if 11 <= h < 15 else 0.30) for h in range(24)}
        data = replace(data, tariff_context=TariffContext(prices={day: prices}))
    if name == "two_dishwashers":
        tasks = [
            TaskRequest(name=n, uid=n, due=day) for n in ("Lave-vaisselle", "Lave-vaisselle étage")
        ]
        profiles_ = dict(data.cycle_profiles)
        for task in ("Lave-vaisselle", "Lave-vaisselle étage"):  # mesurés : pas dans la capture
            profiles_[task] = CycleProfile(energy_kwh=0.9, duration_min=150)
        data = replace(data, due_tasks=(*data.due_tasks, *tasks), cycle_profiles=profiles_)
    if name == "southern":
        data = replace(data, day=date(2026, 7, 15), southern=True)
    return configured(data, profile.home, profile.configuration)


def checked(problem: Problem) -> Plan:
    day = plan_day(problem).day
    assert day.indicators is not None
    assert all(item.explanation is not None for item in day.items)
    codes = [w["code"] for w in day.warnings if isinstance(w, dict)]
    assert "contrainte_impossible" not in codes and "contrainte_non_respectee" not in codes
    slots = {i.device: i for i in day.items if isinstance(i, Slot)}
    washing, drying = slots.get("Lave-linge"), slots.get("Sèche-linge")
    if washing and drying and washing.end_min is not None and drying.start_min is not None:
        assert drying.start_min >= washing.end_min  # le sèche-linge suit le lave-linge
    return day


@pytest.mark.parametrize("name", TESTED)
def test_each_profile_is_loaded_by_import_and_plans(name: str) -> None:
    raw = profiles.document(name)
    found, result = exchange.check(raw)
    assert found is not None and result.issues == []

    checked(from_input(state_of(name)))


@pytest.mark.parametrize("name", TESTED)
def test_each_profile_plans_seven_days_within_the_budget(name: str) -> None:
    first = state_of(name)
    forecast = DayForecast(net_kwh=dict(first.net_kwh), production_kwh=dict(first.production_kwh))
    began = time.perf_counter()
    result = plan_day(from_input(first))
    for offset in range(1, 7):
        data = next_day_input(
            first, first.day + timedelta(days=offset), forecast, first.battery.stored_kwh
        )
        result = plan_day(from_input(data), explained=offset == 1)  # demain expliqué
    assert result.day.indicators is not None
    assert time.perf_counter() - began < BUDGET_S


def test_what_each_profile_changes() -> None:
    no_battery = checked(from_input(state_of("no_battery")))
    assert no_battery.indicators is not None and no_battery.indicators.battery_throughput_kwh == 0

    assert checked(from_input(state_of("no_pool"))).runtimes == []

    tempo = from_input(state_of("tempo"))
    assert tempo.prices_eur_kwh[12] == 0.66 and tempo.prices_eur_kwh[23] == 0.16  # jour rouge
    dynamic = from_input(state_of("dynamic"))
    assert dynamic.prices_eur_kwh[12] == pytest.approx(0.05)
    assert dynamic.prices_eur_kwh[20] == pytest.approx(0.30)

    ev = checked(from_input(state_of("ev")))
    (car,) = [i for i in ev.items if isinstance(i, Slot) and i.device == "Voiture électrique"]
    assert car.energy_kwh == 10 and car.hourly_kwh and max(car.hourly_kwh) < 7

    two = checked(from_input(state_of("two_dishwashers")))
    placed = {i.device for i in two.items if isinstance(i, Slot)}
    assert {"Lave-vaisselle", "Lave-vaisselle étage"} <= placed

    south = from_input(state_of("southern"))
    north = from_input(replace(state_of("southern"), southern=False))
    assert south.runtimes[0].min_hours == 0 < north.runtimes[0].min_hours  # hiver austral
    assert isinstance(checked(south).runtimes[0], RuntimePlan)


def test_profiles_routes(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        listed = api.get("/api/profiles").json()
        assert {p["name"] for p in listed} == {"reference", *TESTED}
        assert all(p["description"] for p in listed)
        tempo = api.get("/api/profiles/tempo").json()
        assert tempo["format"] == exchange.FORMAT
        assert api.get("/api/profiles/unknown").status_code == 404
        imported = api.post("/api/configuration/import", json=tempo)
        assert imported.status_code == 200 and imported.json()["applied"] is True
        assert api.get("/api/configuration").json()["tariff"]["kind"] == "DayColorTariff"
