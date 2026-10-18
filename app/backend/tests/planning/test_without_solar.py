"""Maison sans installation solaire (lot 7.4) : contrat heures creuses seulement, aucune prévision
solaire ; le calcul place les appareils aux heures les moins chères."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from tests.planning.test_assemble import MODEL, TODAY, Reader, client, device, local
from tests.planning.test_runner import context
from wattslot.aggregation import HOUR, QUARTER
from wattslot.configuration import Configuration
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeModel
from wattslot.planning.plan import Plan
from wattslot.planning.runner import run
from wattslot.planning.sources import Forecasts, PlanningSettings, has_production
from wattslot.planning.store import PlanStore
from wattslot.tariff import V1

# Raccordement, lave-linge, chauffe-eau : ni panneaux ni batterie.
NO_SOLAR = HomeModel(
    devices=[
        *(d for d in MODEL.devices if d.kind in (DeviceKind.GRID, DeviceKind.WASHING_MACHINE)),
        device(
            "heater",
            DeviceKind.WATER_HEATER,
            ("sensor.heater_power", Role.POWER_CONSUMED),
            ("sensor.heater_energy", Role.ENERGY_CONSUMED),
        ),
    ]
)
OFF_PEAK = {h for h in range(24) if h < 6 or h >= 22}  # heures creuses de ``tariff.V1``


def reader() -> Reader:
    """14 jours d'historique : achats au réseau, un lavage à 10 h, une chauffe à 14 h."""
    found = Reader()
    for k in range(1, 15):
        day = TODAY - timedelta(days=k)
        for hour in range(24):
            found.add("sensor.imp", HOUR, local(day, hour), energy_kwh=0.4)
            found.add("sensor.exp", HOUR, local(day, hour), energy_kwh=0.0)
        for entity, hour, watts, quarters in (("washer", 10, 800.0, 6), ("heater", 14, 2000.0, 8)):
            for q in range(-1, quarters + 1):
                on = 0 <= q < quarters
                start = local(day, hour) + timedelta(minutes=15 * q)
                found.add(f"sensor.{entity}_power", QUARTER, start, mean=watts if on else 1.0)
                found.add(
                    f"sensor.{entity}_energy",
                    QUARTER,
                    start,
                    energy_kwh=watts / 4000 if on else 0.0,
                )
    return found


def answers() -> dict[str, object]:
    due = TODAY.isoformat()
    items = [
        {
            "uid": uid,
            "summary": name,
            "due": due,
            "description": json.dumps({"type": "a_la_demande"}),
        }
        for uid, name in (("ll", "Lave-linge"), ("ce", "Chauffe-eau"))
    ]
    return {
        "energy/solar_forecast": {},  # aucune prévision, et aucune n'est attendue
        "call_service": {"response": {"todo.maison": {"items": items}}},
        "get_states": [],
    }


def test_a_home_without_panels_needs_no_forecast() -> None:
    assert has_production(MODEL) and has_production(HomeModel()) and has_production(None)
    assert not has_production(NO_SOLAR)

    stub = client({"energy/solar_forecast": RuntimeError("ne doit pas être appelé")})
    forecasts = Forecasts(stub, local(TODAY, 0).tzinfo, PlanningSettings(), production=False)  # type: ignore[arg-type]
    hourly, warnings = asyncio.run(forecasts.hourly(TODAY))

    assert hourly == dict.fromkeys(range(24), 0.0) and warnings == []
    assert stub.calls == []  # type: ignore[attr-defined]


def test_without_panels_the_appliances_go_to_off_peak_hours(tmp_path: Path) -> None:
    ctx = replace(
        context(tmp_path, reader()),
        client=client(answers()),
        model=NO_SOLAR,
        configuration=Configuration(tariff=V1),
    )
    report = asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))

    assert report.errors == []
    store = PlanStore(ctx.database)
    stored = store.load("today")
    assert stored is not None
    plan = stored.plan
    slots = {s.device: s for s in plan.slots}
    assert set(slots) == {"Lave-linge", "Chauffe-eau"}
    for slot in slots.values():
        assert slot.start_min is not None and slot.end_min is not None
        hours = range(slot.start_min // 60, (slot.end_min - 1) // 60 + 1)
        assert set(hours) <= OFF_PEAK, (slot.device, slot.start_min, slot.end_min)
    # Indicateurs : rien de produit, autoconsommation non applicable plutôt que 0 %.
    assert plan.indicators is not None
    assert plan.indicators.self_consumption_percent is None
    assert plan.indicators.export_kwh == 0
    assert all(v == 0 for v in stored.content["production_solaire_horaire"].values())
    for kind in ("tomorrow", "horizon"):
        assert store.load(kind) is not None
    horizon = store.load("horizon")
    assert horizon is not None and len(horizon.content["jours"]) >= 1
    assert all(Plan.from_v1(d).indicators is not None for d in horizon.content["jours"])
