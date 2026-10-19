"""Capture d'un problème sans plan, pour le rejouer (lot 7.3)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.v1_oracle import load as load_state
from tests.v1_oracle import state_named
from wattslot.planning import capture
from wattslot.planning.engine import NoPlanError, Objective, solve
from wattslot.planning.inputs import from_v1
from wattslot.planning.problem import from_input

NOW = datetime(2026, 10, 19, 17, 59, tzinfo=UTC)


def _error() -> NoPlanError:
    state, _ = load_state(state_named("tomorrow_laundry"))
    return NoPlanError("Infeasible", from_input(from_v1(state)), Objective.IMPORT)


def test_a_capture_replays_the_same_problem(tmp_path: Path) -> None:
    error = _error()

    path = capture.save(tmp_path, error, NOW)

    assert path is not None and path.parent == tmp_path / "diagnostic"
    content = capture.load(path)
    assert content["problem"] == error.problem
    assert content["objective"] is Objective.IMPORT
    assert content["captured_at"] == NOW.isoformat()
    assert solve(content["problem"], content["objective"]) == solve(error.problem, Objective.IMPORT)


def test_only_the_latest_captures_are_kept(tmp_path: Path) -> None:
    error = _error()
    paths = [capture.save(tmp_path, error, NOW + timedelta(minutes=k)) for k in range(12)]

    kept = sorted((tmp_path / "diagnostic").glob("no-plan-*.pickle"))

    assert kept == paths[-capture.KEEP :]


def test_a_failed_capture_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "diagnostic").write_text("un fichier, pas un dossier", encoding="utf-8")

    assert capture.save(tmp_path, _error(), NOW) is None
