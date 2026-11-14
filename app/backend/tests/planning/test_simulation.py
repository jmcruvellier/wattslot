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


def test_the_current_hour_is_measured_then_only_its_last_minutes_are_simulated() -> None:
    """Matinée du 06/11/2026 : batterie à 13,5 % pour un plancher à 12 %, calcul à 7h59. Le
    début de l'heure est mesuré (rien ne s'est déchargé) : seule la dernière minute peut encore
    décharger. Avant, chaque calcul rejouait l'heure entière et prévoyait 70 Wh de décharge,
    additionnés d'heure en heure dans le plan."""
    capacity = 5.12

    def run(elapsed: float, change: float) -> list[tuple[int, str, float]]:
        result = simulate(
            {7: -0.45, 8: -0.45},
            0.135 * capacity,
            capacity,
            2.5,
            2.5,
            6,
            22,
            0.95,
            0.95,
            0.12 * capacity,
            first_hour=7,
            elapsed=elapsed,
            elapsed_change_kwh=change,
        )
        return [(m.hour, m.action, m.energy_kwh) for m in result.movements]

    assert run(59 / 60, 0.0) == [(7, "decharge", 0.008), (8, "decharge", 0.065)]
    # Décharge mesurée sur le début de l'heure (0,1 kWh stockés, 95 Wh côté maison), puis le
    # reste au-dessus du plancher (73 Wh) sur la seconde moitié.
    assert run(0.5, -0.1)[0] == (7, "decharge", 0.168)
    # Sans part écoulée : l'heure entière, comme avant.
    assert run(0.0, 0.0)[0] == (7, "decharge", 0.073)


def test_the_exchange_of_the_current_hour_stays_within_its_forecast() -> None:
    """13/11/2026 : calcul à 10h59, déficit prévu de 0,3 kWh sur l'heure, batterie déchargée de
    0,8 kWh côté maison (la maison a consommé plus que prévu). Bilan prévu moins échange
    mesuré donnait 0,5 kWh d'injection, comptés dans le surplus et le coût du plan."""
    capacity = 5.12

    def residual(net: float, change: float) -> float:
        result = simulate(
            {10: net, 11: -0.2},
            0.5 * capacity,
            capacity,
            2.5,
            2.5,
            0,
            24,
            1.0,
            1.0,
            0.12 * capacity,
            first_hour=10,
            elapsed=59 / 60,
            elapsed_change_kwh=change,
        )
        assert result.residual_kwh[11] == pytest.approx(0.0)  # heures suivantes : inchangées
        return result.residual_kwh[10]

    assert residual(-0.3, -0.8) == 0.0  # pas d'injection sans surplus prévu
    assert residual(0.3, 0.8) == 0.0  # pas de soutirage sans déficit prévu
    assert residual(0.3, -0.8) == pytest.approx(0.3)  # ni plus de surplus que prévu
    assert residual(-0.3, 0.8) == pytest.approx(-0.3)  # ni plus d'achat que prévu
    # Mesure que le bilan prévu explique : comptée comme avant.
    assert residual(-0.3, -0.1) == pytest.approx(-0.3 + 0.1 + 0.3 / 60)
