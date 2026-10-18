"""Le banc s'enchaîne et ses requêtes répondent (profil minimal, quelques secondes).

python -m pytest bench/tests
"""

from pathlib import Path

import pytest

from bench.backends import EmbeddedBackend
from bench.data import aggregate_nquads, count_lines, day_start, signal
from bench.model import Kind, build_home
from bench.run import check_thresholds, run


def test_tiny_profile_runs_and_every_query_returns_rows(tmp_path: Path) -> None:
    result = run("tiny", lambda name: EmbeddedBackend(tmp_path / name))

    for organization in ("single", "partitioned"):
        for name, values in result.queries[organization].items():
            assert values["rows"] > 0, f"{organization}/{name} ne renvoie rien"
    assert result.ingestion["batch_triples"] > 0
    assert result.loads["raw"]["triples"] > 0


def test_thresholds_report_slow_queries(tmp_path: Path) -> None:
    result = run("tiny", lambda name: EmbeddedBackend(tmp_path / name))

    assert check_thresholds(result, {"jour": 1000.0}) == []
    assert check_thresholds(result, {"jour": 0.0}) != []


def test_energy_aggregates_match_the_counter() -> None:
    sensor = next(s for s in build_home(8, 10, 1) if s.kind is Kind.ENERGY)
    data, _ = count_lines(aggregate_nquads([sensor], 0, 3600, lambda t: "urn:g"))
    deltas = [
        float(line.split('"')[1]) for line in data.decode().splitlines() if "energyKwh" in line
    ]
    day = day_start(0)
    expected = signal(sensor, day_start(1)) - signal(sensor, day)

    assert len(deltas) == 24
    assert sum(deltas) == pytest.approx(expected, abs=1e-3)
