"""Calcul selon la configuration de la maison (lot 3.1) : piscine et équipements pris en compte."""

import asyncio
from dataclasses import replace
from pathlib import Path

from tests.planning.test_assemble import MODEL, TODAY, local
from tests.planning.test_runner import context, reader_with_history
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.planning.plan import Plan
from wattslot.planning.runner import run
from wattslot.planning.store import PlanStore

POOL_DEVICE = HomeDevice(
    key="pool",
    kind=DeviceKind.POOL_PUMP,
    name="Filtration",
    sensors=[HomeSensor(entity_id="sensor.pool_power", role=Role.POWER_CONSUMED)],
)
WITH_POOL = HomeModel(devices=[*MODEL.devices, POOL_DEVICE])


def plans(tmp_path: Path, model: HomeModel, configuration: Configuration) -> list[Plan]:
    ctx = replace(
        context(tmp_path, reader_with_history()), model=model, configuration=configuration
    )
    report = asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))
    assert report.errors == []
    store = PlanStore(ctx.database)
    found = []
    for kind in ("today", "tomorrow"):
        stored = store.load(kind)
        assert stored is not None
        found.append(stored.plan)
    horizon = store.load("horizon")
    assert horizon is not None
    return found + [Plan.from_v1(day) for day in horizon.content["jours"]]


def pools(plan: Plan) -> list[str]:
    return [r.device for r in plan.runtimes]


def test_no_pool_in_the_home_no_filtration_planned(tmp_path: Path) -> None:
    found = plans(tmp_path, MODEL, Configuration())

    assert all(pools(plan) == [] for plan in found)
    today = found[0].to_v1()
    # Recommandation tirée des explications (lot 3.7) : pas de durée à placer.
    assert "Aucune durée de fonctionnement à placer." in today["texte_recommandation"]


def test_a_pool_of_the_home_is_planned_unless_set_otherwise(tmp_path: Path) -> None:
    # Élément du plan au nom de l'équipement (lot 3.4).
    planned = plans(tmp_path / "a", WITH_POOL, Configuration())
    assert all(pools(p) == ["Filtration"] for p in planned)

    off = Configuration(
        devices=[DeviceSettings(key="pool", behavior=Behavior.RUNTIME, planned=False)]
    )
    assert all(pools(p) == [] for p in plans(tmp_path / "b", WITH_POOL, off))

    observed = Configuration(devices=[DeviceSettings(key="pool", behavior=Behavior.UNCONTROLLED)])
    assert all(pools(p) == [] for p in plans(tmp_path / "c", WITH_POOL, observed))


def test_tasks_of_a_device_left_out_are_not_planned(tmp_path: Path) -> None:
    planned = plans(tmp_path / "a", MODEL, Configuration())
    assert "Lave-linge" in [s.device for s in planned[0].slots]

    off = Configuration(
        devices=[DeviceSettings(key="washer", behavior=Behavior.CYCLE, planned=False)]
    )
    left_out = plans(tmp_path / "b", MODEL, off)
    assert all("Lave-linge" not in [s.device for s in p.slots] for p in left_out)
    assert left_out[0].to_v1()["profils_cycles"] == {}
