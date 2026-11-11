"""Un calcul complet : le jour (fusionné d'un calcul à l'autre), demain, l'horizon, la bascule."""

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from tests.planning.test_assemble import MODEL, TODAY, Reader, client, local
from tests.planning.test_journal import raw_cycle
from wattslot.aggregation import HOUR, QUARTER
from wattslot.planning import choices
from wattslot.planning.plan import Plan
from wattslot.planning.runner import (
    Context,
    frozen_cycles,
    past_pool,
    planned_reasons,
    refresh_actual,
    run,
)
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


def test_the_reasons_of_the_previous_plan_are_kept_without_launched() -> None:
    """D'un recalcul à l'autre, un cycle lancé garde les raisons de son placement : celles du
    plan précédent, sans « lancé » (qui serait sinon répété)."""
    solar = {"code": "solar_share", "params": {"percent": 80}}
    launched = {"code": "launched", "params": {"time": "09h59"}}
    old = {
        "planning": [
            {
                "equipement": "Lave-linge",
                "heure_debut": 10,
                # « Heure gardée » ne suit pas un appareil une fois lancé.
                "explication": {"raisons": [{"code": "announced_kept"}, solar]},
            },
            {
                "equipement": "Sèche-linge",
                "heure_debut": 12,
                "explication": {"raisons": [launched, solar]},
            },
            {
                "equipement": "Lave-vaisselle",
                "heure_debut": 9,
                "explication": {"raisons": [launched]},
            },
            {"equipement": "Chauffe-eau", "heure_debut": 13},
        ]
    }

    found = planned_reasons(Plan.from_v1(old))

    assert {name: [r.code for r in reasons] for name, reasons in found.items()} == {
        "Lave-linge": ["solar_share"],
        "Sèche-linge": ["solar_share"],
    }
    assert planned_reasons(None) == {}


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

    # Calcul de l'heure suivante, une fois le lave-linge commencé (relevés de puissance depuis
    # le départ annoncé) : son bloc reste à cette heure.
    raw_cycle(ctx.raw, TODAY, local(TODAY, washer_start // 60, washer_start % 60), 90, 0.9, 50.0)
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


def test_a_recommendation_that_was_not_followed_is_placed_again(tmp_path: Path) -> None:
    """Le départ annoncé est passé et le lave-linge, mesuré, n'a pas tourné : son créneau n'est
    pas tenu pour commencé. L'appareil est replacé plus tard, et rien ne dit qu'il est lancé."""
    ctx = context(tmp_path, reader_with_history())
    store = PlanStore(ctx.database)
    asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))
    today = store.load("today")
    assert today is not None
    washer_start = next(
        i["debut_min"] for i in today.content["planning"] if i["equipement"] == "Lave-linge"
    )

    later = local(TODAY, washer_start // 60 + 1, 5)
    asyncio.run(run(ctx, later))

    again = store.load("today")
    assert again is not None
    item = next(i for i in again.content["planning"] if i["equipement"] == "Lave-linge")
    assert item["debut_min"] >= later.hour * 60 + later.minute
    assert "Lancé" not in (item.get("justification") or "")


def test_a_chosen_start_moves_a_planned_slot_already_in_the_past(tmp_path: Path) -> None:
    """Un départ choisi pour aujourd'hui déplace même un créneau déjà passé du plan précédent,
    tant que l'équipement n'a pas tourné : la frise le propose, le calcul doit le suivre."""
    reader = reader_with_history()
    ctx = context(tmp_path, reader)
    store = PlanStore(ctx.database)

    asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))
    today = store.load("today")
    assert today is not None
    planning = {item["equipement"]: item for item in today.content["planning"]}
    washer_start = planning["Lave-linge"]["debut_min"]

    # Le créneau prévu est passé et l'appareil n'a pas démarré : on choisit un autre départ.
    later = local(TODAY, washer_start // 60 + 1, 5)
    chosen = (washer_start // 60 + 3) * 60
    choices.choose(ctx.database, TODAY, "Lave-linge", chosen, later)

    asyncio.run(run(ctx, later))
    again = store.load("today")
    assert again is not None
    item = next(i for i in again.content["planning"] if i["equipement"] == "Lave-linge")
    assert item["debut_min"] == chosen


def test_a_start_chosen_for_tomorrow_moves_the_task_to_tomorrow(tmp_path: Path) -> None:
    """Départ choisi pour demain à 1 h : la tâche quitte aujourd'hui et le plan de demain la
    place à ce départ ; le calcul de l'horizon reçoit les choix de ses jours."""
    reader = reader_with_history()
    ctx = context(tmp_path, reader)
    store = PlanStore(ctx.database)
    tomorrow = TODAY + timedelta(days=1)
    choices.choose(ctx.database, tomorrow, "Lave-linge", 60, local(TODAY, 9), today=TODAY)

    report = asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))

    assert report.errors == [] and store.assignments(TODAY)["ll"].day == tomorrow
    today = store.load("today")
    assert today is not None
    assert "Lave-linge" not in {i["equipement"] for i in today.content["planning"]}
    planned = store.load("tomorrow")
    assert planned is not None
    item = next(i for i in planned.content["planning"] if i["equipement"] == "Lave-linge")
    assert item["debut_min"] == 60


def test_a_cycle_started_in_the_evening_ends_the_next_day(tmp_path: Path) -> None:
    """Lave-linge lancé à 23 h (départ choisi) : il finit à 0 h 30 ; la vue Demain reçoit sa
    fin comme consommation déjà décidée, et le jour suivant la garde après minuit."""
    reader = reader_with_history()
    ctx = context(tmp_path, reader)
    store = PlanStore(ctx.database)
    choices.choose(ctx.database, TODAY, "Lave-linge", 23 * 60, local(TODAY, 21))

    report = asyncio.run(run(ctx, local(TODAY, 21, 5), manual=True))

    assert report.errors == []
    today = store.load("today")
    assert today is not None
    washer = next(i for i in today.content["planning"] if i["equipement"] == "Lave-linge")
    assert (washer["debut_min"], washer["fin_min"]) == (23 * 60, 24 * 60 + 30)
    tomorrow = store.load("tomorrow")
    assert tomorrow is not None
    carried = tomorrow.content["suite_veille"]
    assert [(c["equipement"], c["fin_min"]) for c in carried] == [("Lave-linge", 30)]
    assert carried[0]["energie_kwh"] > 0

    asyncio.run(run(ctx, local(TODAY + timedelta(days=1), 0, 10)))
    after = store.load("today")
    assert after is not None and after.day == TODAY + timedelta(days=1)
    assert [c["equipement"] for c in after.content["suite_veille"]] == ["Lave-linge"]
    # Calcul suivant de la journée : la fin de la veille reste gardée.
    asyncio.run(run(ctx, local(TODAY + timedelta(days=1), 1, 10)))
    again = store.load("today")
    assert again is not None
    assert [c["equipement"] for c in again.content["suite_veille"]] == ["Lave-linge"]


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
