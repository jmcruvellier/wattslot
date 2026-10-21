"""Un calcul complet : le jour (fusionné d'un calcul à l'autre), demain, l'horizon, la bascule."""

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from tests.planning.test_assemble import MODEL, TODAY, Reader, client, local
from wattslot.aggregation import HOUR, QUARTER
from wattslot.planning.plan import Plan
from wattslot.planning.runner import Context, frozen_cycles, past_pool, refresh_actual, run
from wattslot.planning.sources import PlanningSettings
from wattslot.planning.store import PlanStore, dumps, loads
from wattslot.storage.database import open_database
from wattslot.storage.raw import RawStores


def reader_with_history() -> Reader:
    reader = Reader()
    for k in range(1, 15):
        day = TODAY - timedelta(days=k)
        for hour in range(24):
            start = local(day, hour)
            for entity, kwh in (("sensor.imp", 0.4), ("sensor.exp", 0.0), ("sensor.chg", 0.0)):
                reader.add(entity, HOUR, start, energy_kwh=kwh)
            reader.add("sensor.dis", HOUR, start, energy_kwh=0.0)
        for q in range(-1, 7):
            start = local(day, 10) + timedelta(minutes=15 * q)
            on = 0 <= q < 6
            reader.add("sensor.washer_power", QUARTER, start, mean=800.0 if on else 1.0)
            reader.add("sensor.washer_energy", QUARTER, start, energy_kwh=0.05 if on else 0.0)
    for hour in range(9):
        reader.add("sensor.soc", HOUR, local(TODAY, hour), last=40.0, max=40.0, mean=40.0)
    return reader


def answers() -> dict[str, object]:
    wh_hours = {
        local(TODAY + timedelta(days=d), h).isoformat(): 1500
        for d in range(7)
        for h in range(9, 18)
    }
    items = [
        {"uid": "ll", "summary": "Lave-linge", "description": json.dumps({"type": "a_la_demande"})}
    ]
    return {
        "energy/solar_forecast": {"x": {"wh_hours": wh_hours}},
        "call_service": {"response": {"todo.maison": {"items": items}}},
        "get_states": [{"entity_id": "sensor.soc", "state": "45"}],
    }


def context(tmp_path: Path, reader: Reader) -> Context:
    return Context(
        client=client(answers()),
        model=MODEL,
        reader=reader,
        raw=RawStores(tmp_path, "Europe/Paris"),
        database=open_database(tmp_path),
        settings=PlanningSettings(todo_entity="todo.maison"),
    )


def test_store_reads_hours_back_as_integers() -> None:
    content = {
        "soc_horaire_kwh": {0: 1.0, 23: 2.0},
        "planning": [{"equipement": "x"}],
        "jour": date(2026, 1, 2),
    }
    assert loads(dumps(content)) == {**content, "jour": "2026-01-02"}


def test_frozen_cycles_and_past_pool_come_from_the_previous_plan() -> None:
    old = {
        "planning": [
            {
                "equipement": "Lave-linge",
                "heure_debut": 10,
                "heure_fin": 12,
                "debut_min": 600,
                "fin_min": 680,
            },
            {"equipement": "Sèche-linge", "heure_debut": 15, "heure_fin": 17},
            {"equipement": "Batterie", "heure_debut": 0},
            {
                "equipement": "Piscine (filtration)",
                "segments": [
                    {"heure_debut": 0, "heure_fin": 11, "mode": "off"},
                    {"heure_debut": 11, "heure_fin": 14, "mode": "eco"},
                    {"heure_debut": 14, "heure_fin": 24, "mode": "off"},
                ],
            },
        ]
    }

    plan = Plan.from_v1(old)
    assert [c.name for c in frozen_cycles(plan, 13)] == ["Lave-linge"]
    assert past_pool(plan, 13)[12] == "eco" and 13 not in past_pool(plan, 13)


def test_a_full_run_then_an_hourly_run_then_the_next_day(tmp_path: Path) -> None:
    reader = reader_with_history()
    ctx = context(tmp_path, reader)
    store = PlanStore(ctx.database)

    report = asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))

    assert report.errors == [] and report.horizon_days == 5
    today = store.load("today")
    assert today is not None and today.day == TODAY and today.manual
    assert "Équipements à lancer aujourd'hui :" in today.content["texte_recommandation"]
    planning = {item["equipement"]: item for item in today.content["planning"]}
    washer_start = planning["Lave-linge"]["debut_min"]
    assert planning["Batterie"]["soc_initial_kwh"] == 2.0  # SoC de 8 h (40 %), pas l'instant
    tomorrow = store.load("tomorrow")
    assert tomorrow is not None
    tomorrow_battery = next(
        i for i in tomorrow.content["planning"] if i["equipement"] == "Batterie"
    )
    assert tomorrow_battery["soc_initial_kwh"] == planning["Batterie"]["soc_final_kwh"]
    assert store.assignments(TODAY)["ll"].day == TODAY
    actual = today.content["donnees_reelles_cache"]
    assert actual["heure_maj_iso"] == local(TODAY, 9, 20).isoformat() and not actual["manuel"]

    # Bouton « Rafraîchir » : données réelles relues, sans calcul.
    refreshed = refresh_actual(ctx.model, ctx.raw, ctx.database, local(TODAY, 9, 40))
    assert refreshed is not None and refreshed["manuel"]
    kept = store.load("today")
    assert kept is not None and kept.content["planning"] == today.content["planning"]
    assert kept.content["donnees_reelles_cache"] == refreshed
    # Relecture périodique du planificateur : pas « manuelle ».
    periodic = refresh_actual(ctx.model, ctx.raw, ctx.database, local(TODAY, 9, 45), manual=False)
    assert periodic is not None and not periodic["manuel"]

    # Calcul de l'heure suivante, une fois le lave-linge commencé : son bloc reste gelé.
    later = local(TODAY, (washer_start // 60) + 1, 5)
    asyncio.run(run(ctx, later))
    again = store.load("today")
    assert again is not None and not again.manual
    item = next(i for i in again.content["planning"] if i["equipement"] == "Lave-linge")
    assert item["debut_min"] == washer_start

    # Lendemain : le plan de la veille est archivé.
    asyncio.run(run(ctx, local(TODAY + timedelta(days=1), 0, 1)))
    yesterday = store.load("yesterday")
    assert yesterday is not None and yesterday.day == TODAY
    completed = yesterday.content["donnees_reelles_cache"]
    assert completed["heure_maj_iso"] == local(TODAY + timedelta(days=1), 0).isoformat()
    assert (
        refresh_actual(ctx.model, ctx.raw, ctx.database, local(TODAY + timedelta(days=2), 1))
        is None
    )
    current = store.load("today")
    assert current is not None and current.day == TODAY + timedelta(days=1)
    assert current.content["derniere_execution"]["manuel"] is False


def test_a_plan_computed_during_the_history_import_is_provisional(tmp_path: Path) -> None:
    """Reprise de l'historique de HA en cours : le plan le note (plan provisoire), puis ne le
    note plus au calcul suivant, une fois la reprise finie (essai du 21/10/2026)."""

    class ImportingReader(Reader):
        def __init__(self) -> None:
            super().__init__()
            self.pending = ["sensor.imp", "sensor.exp"]

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(history=SimpleNamespace(pending=self.pending))

    reader = ImportingReader()
    reader.__dict__.update(reader_with_history().__dict__)
    ctx = context(tmp_path, reader)
    store = PlanStore(ctx.database)

    asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))
    first = store.load("today")
    reader.pending = []
    asyncio.run(run(ctx, local(TODAY, 10, 5)))
    second = store.load("today")

    assert first is not None and first.content["historique_en_reprise"] == 2
    assert second is not None and "historique_en_reprise" not in second.content


def test_planning_routes_without_home_assistant(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from tests.test_health import _settings
    from wattslot.main import create_app

    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.post("/api/planning/run").status_code == 503
        assert api.post("/api/planning/actual").status_code == 503
        assert api.get("/api/planning/plan").status_code == 404
        assert api.get("/api/planning/plan?view=autre").status_code == 422
