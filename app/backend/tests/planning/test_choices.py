"""Départs choisis par l'utilisateur parmi ceux que le plan propose : imposés au calcul,
expliqués, gardés en base pour la journée."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.v1_oracle import STATES, load
from wattslot.planning import choices
from wattslot.planning.engine import Objective, indicators, load_kwh, plan_day, simulate_plan
from wattslot.planning.explain import ALTERNATIVES, explain
from wattslot.planning.inputs import CycleProfile, from_v1
from wattslot.planning.plan import Indicators, Slot
from wattslot.planning.problem import Task, from_input
from wattslot.storage.database import open_database


def _task(chosen: int | None) -> Task:
    return Task(
        name="Lave-linge",
        key="lave-linge",
        energy_kwh=1.0,
        cycle_min=90,
        slot_min=90,
        shape=None,
        priority=3,
        earliest_min=600,
        chosen_min=chosen,
    )


def test_a_chosen_start_is_the_only_candidate_while_it_is_possible() -> None:
    assert _task(840).candidates() == [840]
    assert _task(840).candidates(chosen=False)[:2] == [600, 660]
    assert _task(540).candidates()[0] == 600  # déjà passé : le calcul reprend la main
    assert _task(1400).candidates()[-1] == 1320  # finirait après minuit : ignoré


def test_the_plan_offers_other_starts_and_keeps_the_one_chosen() -> None:
    state, _ = load(STATES[11])  # lave-linge et sèche-linge à placer, journée ensoleillée
    data = from_v1(state)
    day = plan_day(from_input(data), Objective.COST).day
    slots = {
        i.device: i
        for i in day.items
        if isinstance(i, Slot) and i.explanation and i.explanation.alternatives
    }
    device, slot = next(iter(slots.items()))
    explanation = slot.explanation
    assert explanation is not None
    others = explanation.alternatives
    assert 1 <= len(others) <= ALTERNATIVES
    assert explanation.alternative == others[0]
    assert all(other.start_min != slot.start_min for other in others)
    assert not explanation.chosen

    chosen = others[-1].start_min
    again = plan_day(from_input(replace(data, chosen_starts={device: chosen})), Objective.COST)

    kept = next(i for i in again.day.items if isinstance(i, Slot) and i.device == device)
    assert again.plan.starts[device] == chosen
    assert kept.explanation is not None and kept.explanation.chosen
    assert kept.explanation.reasons[0].code == "chosen"
    assert "choisi par vous" in (kept.justification or "")
    # Les autres départs restent proposés, dont celui du calcul : on peut y revenir.
    assert (
        slot.start_min in {o.start_min for o in kept.explanation.alternatives}
        or len(kept.explanation.alternatives) == ALTERNATIVES
    )


def test_choices_are_kept_for_the_day_only(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    now = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
    choices.choose(database, date(2026, 10, 20), "Chauffe-eau", 1200, now)
    choices.choose(database, date(2026, 10, 21), "Chauffe-eau", 1260, now)
    choices.choose(database, date(2026, 10, 21), "Chauffe-eau", 1200, now)  # remplacé

    assert choices.load(database, date(2026, 10, 21)) == {"Chauffe-eau": 1200}
    assert choices.load(database, date(2026, 10, 20)) == {}  # jour passé : oublié
    assert choices.clear(database, date(2026, 10, 21), "Chauffe-eau")
    assert not choices.clear(database, date(2026, 10, 21), "Chauffe-eau")


def test_the_choice_of_a_closed_request_is_forgotten(tmp_path: Path) -> None:
    """20/11/2026 : départ du lave-linge choisi à 3 h, lessive faite, nouvelle lessive demandée
    le matin. Le choix de 3 h valait encore pour elle."""
    database = open_database(tmp_path)
    day, now = date(2026, 11, 20), datetime(2026, 11, 20, 7, 0, tzinfo=UTC)
    choices.choose(database, day, "Lave Linge", 180, now, request="app-41")
    choices.choose(database, day, "Sèche Linge", 600, now, request="app-45")
    choices.choose(database, day, "Chauffe-Eau", 720, now)  # choix d'avant : sans demande

    assert choices.forget_closed(database, day, {"app-45", "app-47"}) == 1

    assert choices.load(database, day) == {"Sèche Linge": 600, "Chauffe-Eau": 720}


def test_a_choice_keeps_the_request_of_its_block() -> None:
    planning: list[dict[str, object]] = [
        {"equipement": "Batterie"},
        {"equipement": "Lave Linge", "demande": "app-41"},
        {"equipement": "Lave Linge", "rang": 2, "demande": "app-47"},
        {"equipement": "Chauffe-Eau"},
    ]
    assert choices.request_of(planning, "Lave Linge") == "app-41"
    assert choices.request_of(planning, "Lave Linge #2") == "app-47"
    assert choices.request_of(planning, "Chauffe-Eau") is None
    assert choices.request_of(planning, "Sèche Linge") is None


def test_routes(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(choices.router)
    app.state.database = open_database(tmp_path)
    app.state.raw = SimpleNamespace(zone=ZoneInfo("Europe/Paris"))
    with TestClient(app) as api:
        assert (
            api.post(
                "/api/planning/choices", json={"device": "Chauffe-eau", "start_min": 1200}
            ).status_code
            == 201
        )
        assert api.get("/api/planning/choices").json() == [
            {"device": "Chauffe-eau", "start_min": 1200, "day": None}
        ]
        assert (
            api.post(
                "/api/planning/choices", json={"device": "Chauffe-eau", "start_min": 1440}
            ).status_code
            == 422
        )
        assert api.delete("/api/planning/choices/Chauffe-eau").status_code == 204
        assert api.delete("/api/planning/choices/Chauffe-eau").status_code == 404


def test_choices_for_the_following_days(tmp_path: Path) -> None:
    """Un départ choisi pour demain ou un jour de l'horizon n'efface pas celui d'aujourd'hui."""
    database = open_database(tmp_path)
    now = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
    today, tomorrow = date(2026, 10, 21), date(2026, 10, 22)
    choices.choose(database, today, "Lave-linge", 900, now)
    choices.choose(database, tomorrow, "Chauffe-eau", 60, now, today=today)

    assert choices.load(database, today) == {"Lave-linge": 900}
    assert choices.load_days(database, [today, tomorrow, date(2026, 10, 23)]) == {
        today: {"Lave-linge": 900},
        tomorrow: {"Chauffe-eau": 60},
    }


def test_routes_for_the_following_days(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(choices.router)
    app.state.database = open_database(tmp_path)
    app.state.raw = SimpleNamespace(zone=ZoneInfo("Europe/Paris"))
    today = datetime.now(UTC).astimezone(ZoneInfo("Europe/Paris")).date()
    tomorrow, last = (today + timedelta(days=1)).isoformat(), today + timedelta(days=6)
    with TestClient(app) as api:
        body = {"device": "Chauffe-eau", "start_min": 60, "day": tomorrow}
        assert api.post("/api/planning/choices", json=body).status_code == 201
        assert api.get("/api/planning/choices").json() == []
        assert api.get("/api/planning/choices", params={"day": tomorrow}).json() == [body]
        late = {**body, "day": (last + timedelta(days=1)).isoformat()}
        assert api.post("/api/planning/choices", json=late).status_code == 422
        early = {**body, "day": (today - timedelta(days=1)).isoformat()}
        assert api.post("/api/planning/choices", json=early).status_code == 422
        assert (
            api.post("/api/planning/choices", json={**body, "day": last.isoformat()}).status_code
            == 201
        )
        assert api.delete("/api/planning/choices/Chauffe-eau").status_code == 404
        gone = api.delete("/api/planning/choices/Chauffe-eau", params={"day": tomorrow})
        assert gone.status_code == 204


def test_a_cheaper_start_set_aside_for_the_battery_says_so() -> None:
    """Charge complète due et un autre départ qui noterait mieux : la raison le dit, au lieu de
    « placé pour le coût le plus bas »."""
    state, _ = load(STATES[11])
    problem = from_input(from_v1(state))
    problem = replace(problem, battery=replace(problem.battery, full_priority=True))
    result = plan_day(problem, Objective.COST, explained=False)
    starts = dict(result.plan.starts)

    def evaluate(moved: dict[str, int]) -> Indicators:
        found = indicators(problem, simulate_plan(problem, replace(result.plan, starts=moved)))
        # Tout autre départ noterait mieux que celui du plan.
        return found if moved == starts else found.model_copy(update={"cost_eur": -1.0})

    day = explain(
        problem,
        result.day,
        starts,
        load_kwh(problem, result.plan),
        "cost",
        evaluate,
        lambda found: found.cost_eur,
    )

    codes = {
        i.device: [r.code for r in i.explanation.reasons]
        for i in day.items
        if isinstance(i, Slot) and i.explanation and i.device in starts
    }
    assert codes and all(
        c[0] == "full_charge_first" and "objective" not in c for c in codes.values()
    )


def test_a_chosen_start_wins_over_the_cycle_to_follow() -> None:
    """20/11/2026 : sèche-linge « après le lave-linge », départ choisi à 10 h, puis une
    nouvelle lessive demandée à 8 h 21. Elle ne pouvait pas finir avant 10 h : le sèche-linge
    n'était plus placé du tout (« pas assez de temps pour un cycle complet »), et son ancien
    bloc de 11 h restait affiché. Un départ choisi est une décision : il passe avant la suite."""
    data = from_v1(load(next(p for p in STATES if "synthetic_sunny_h00" in p.stem))[0])
    now = datetime.combine(data.day, datetime.min.time()).astimezone() + timedelta(
        hours=8, minutes=21
    )
    asked = replace(
        data,
        first_hour=8,
        real_updated_at=now,
        cycle_profiles={
            **data.cycle_profiles,
            "Lave-linge": CycleProfile(0.43, 120.0),
            "Sèche-linge": CycleProfile(1.48, 240.0),
        },
    )

    def starts(chosen: dict[str, int]) -> dict[str, int | None]:
        day = plan_day(from_input(replace(asked, chosen_starts=chosen))).day
        assert not [w for w in day.warnings if isinstance(w, dict) and "heures" in w["code"]]
        return {i.device: i.start_min for i in day.items if isinstance(i, Slot)}

    free = starts({})
    washer_end = (free["Lave-linge"] or 0) + 120
    assert washer_end > 600 and (free["Sèche-linge"] or 0) >= washer_end  # la suite, sans choix
    assert starts({"Sèche-linge": 600})["Sèche-linge"] == 600
