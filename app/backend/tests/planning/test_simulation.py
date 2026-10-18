"""Simulation de la batterie : la réécriture donne les mêmes résultats que la v1 (oracle)."""

import random

import pytest

from tests.v1_oracle import v1
from wattslot.planning.simulation import simulate

SOC_MIN_PERCENT = v1("noeud_calcul.SOC_MIN_PERCENT")


@pytest.mark.parametrize("seed", range(300))
def test_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    first = rng.randint(0, 23)
    net = {h: rng.uniform(-2.5, 3.0) for h in range(first, 24)}
    capacity = rng.choice([0.0, rng.uniform(2, 15)])
    stored = rng.uniform(0, capacity)
    charge_kw, discharge_kw = rng.uniform(0.3, 3), rng.uniform(0.3, 3)
    active_from = rng.randint(0, 12)
    active_to = rng.randint(active_from, 24)
    measured = rng.random() < 0.5
    efficiency_c = rng.uniform(0.7, 1.0) if measured else None
    efficiency_d = rng.uniform(0.7, 1.0) if measured else None
    round_trip = rng.choice([None, rng.uniform(70, 95)])
    per_direction = (round_trip / 100) ** 0.5 if round_trip else 1.0

    # ``_simuler_soc_batterie`` de la v1 ; le net qu'elle reçoit devient le résidu après batterie.
    movements, end, soc, expected_net = v1(
        "noeud_calcul.simulation",
        net,
        stored,
        capacity,
        charge_kw,
        discharge_kw,
        active_from,
        active_to,
        rendement_round_trip_percent=round_trip,
        heure_debut_simulation=first,
        rendement_charge=efficiency_c,
        rendement_decharge=efficiency_d,
    )
    run = simulate(
        net,
        stored,
        capacity,
        charge_kw,
        discharge_kw,
        active_from,
        active_to,
        efficiency_c or per_direction,
        efficiency_d or per_direction,
        capacity * SOC_MIN_PERCENT / 100,
        first_hour=first,
    )

    assert [(m.hour, m.action, m.energy_kwh) for m in run.movements] == [
        (m["heure"], m["action"], m["energie_kwh"]) for m in movements
    ]
    assert run.end_kwh == pytest.approx(end, abs=1e-9)
    assert run.soc_kwh == pytest.approx(soc, abs=1e-9)
    assert run.residual_kwh == pytest.approx(expected_net, abs=1e-9)
