"""Heure limite d'une demande (issue 273) : « terminé avant 12 h », propre à la demande."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.planning.test_time_constraints import HEATER, codes, planned, slot, state
from tests.test_health import _settings
from tests.test_user_requests import CREATED, WASHER
from wattslot import user_requests
from wattslot.languages import LANGUAGES
from wattslot.main import create_app
from wattslot.planning.assignment import decide
from wattslot.planning.explain import render
from wattslot.planning.inputs import PlanningInput, TaskRequest
from wattslot.planning.warning_texts import warning_text
from wattslot.storage.database import open_database

TODAY = date(2026, 10, 12)
TOMORROW = TODAY + timedelta(days=1)
CYCLES = {"Lave-vaisselle": (1.2, 120.0)}
DULL: dict[date, dict[int, float]] = {TODAY: {}, TOMORROW: {}}


def dishwasher(finish_hour: int | None) -> TaskRequest:
    return TaskRequest(
        name="Lave-vaisselle",
        uid="app-1",
        on_demand=True,
        needed_since=TODAY,
        finish_hour=finish_hour,
    )


def with_limit(hour: int) -> PlanningInput:
    """État capturé n° 0 (calcul à partir de 6 h), le chauffe-eau à finir avant ``hour``."""
    data = state()
    tasks = tuple(replace(t, finish_hour=hour) if t.name == HEATER else t for t in data.due_tasks)
    assert any(t.finish_hour == hour for t in tasks)
    return replace(data, due_tasks=tasks)


def test_a_request_is_stored_with_its_finish_hour(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    first = user_requests.ask(database, "washer", None, CREATED, finish_hour=12)
    assert first.finish_hour == 12

    _, waiting = user_requests.tasks(database, [WASHER], [], TODAY)
    assert [t.finish_hour for t in waiting] == [12]

    # Redemander change la date et l'heure limite de la demande en attente.
    again = user_requests.ask(database, "washer", TOMORROW, CREATED, finish_hour=18)
    assert (again.id, again.latest, again.finish_hour) == (first.id, TOMORROW, 18)
    cleared = user_requests.ask(database, "washer", TOMORROW, CREATED)
    assert cleared.id == first.id and cleared.finish_hour is None


def test_the_route_refuses_an_hour_out_of_the_day(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        for hour in (0, 25):
            answer = api.post("/api/requests", json={"device": "washer", "finish_hour": hour})
            assert answer.status_code == 422
            assert answer.json()["detail"][0]["loc"] == ["body", "finish_hour"]


def test_the_cycle_of_a_request_ends_before_its_finish_hour() -> None:
    free = slot(planned(state()), HEATER)
    day = planned(with_limit(10))
    found = slot(day, HEATER)

    assert free.end_min is not None and free.end_min > 10 * 60  # sans limite : plus tard
    assert found.end_min is not None and found.end_min <= 10 * 60
    assert "heure_limite_depassee" not in codes(day)
    assert found.explanation is not None
    reason = next(r for r in found.explanation.reasons if r.code == "finish_before")
    assert reason.params == {"hour": 10}
    assert "Terminé avant 10 h, comme demandé." in render(found.explanation, "fr")
    for lang in LANGUAGES:
        assert "{" not in render(found.explanation, lang)


def test_a_finish_hour_that_cannot_be_met_is_reported_and_the_cycle_placed() -> None:
    """Calcul à partir de 6 h, cycle à finir avant 6 h : placé quand même, et signalé."""
    day = planned(with_limit(6))
    found = slot(day, HEATER)

    assert found.end_min is not None and found.end_min > 6 * 60
    warning = next(
        w for w in day.warnings if isinstance(w, dict) and w["code"] == "heure_limite_depassee"
    )
    assert warning["params"] == {
        "equipement": HEATER,
        "heure_limite": 6,
        "fin_min": found.end_min % (24 * 60),
    }
    assert found.explanation is not None
    assert "finish_before" not in [r.code for r in found.explanation.reasons]
    assert warning_text(warning, "fr").startswith(
        "Chauffe-eau : ne sera pas terminé avant 6h comme demandé (fin prévue à "
    )
    for lang in LANGUAGES:
        text = warning_text(warning, lang)
        assert text != "heure_limite_depassee" and "{" not in text


def test_an_evening_request_to_finish_before_noon_goes_to_tomorrow() -> None:
    """Demande faite à 20 h, à finir avant 12 h : aucun cycle d'aujourd'hui ne la tient, la
    tâche va à demain."""
    free, _ = decide([dishwasher(None)], DULL, TODAY, 20, CYCLES, {}, set())
    limited, reports = decide([dishwasher(12)], DULL, TODAY, 20, CYCLES, {}, set())

    assert free["app-1"].day == TODAY
    assert limited["app-1"].day == TOMORROW
    assert [r["params"]["equipement"] for r in reports] == ["Lave-vaisselle"]


def test_a_finish_hour_no_day_can_meet_keeps_the_request_today() -> None:
    """Cycle de 2 h à finir avant 1 h : aucun jour ne convient, la tâche reste sur aujourd'hui,
    où le calcul la place au mieux et signale le dépassement."""
    found, reports = decide([dishwasher(1)], DULL, TODAY, 20, CYCLES, {}, set())

    assert found["app-1"].day == TODAY and reports == []
