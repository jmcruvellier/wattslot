"""Jours annoncés (Tempo, EJP) : autres états reconnus par couleur, modèle EJP."""

from datetime import date
from pathlib import Path

from wattslot import configuration, templates
from wattslot.configuration import Configuration
from wattslot.storage.graph import GraphStore
from wattslot.tariff import ColorPrices, Tariff, TariffContext, TariffKind, problems

PEAK, NEXT = date(2026, 12, 3), date(2026, 12, 4)
EJP = templates.load("ejp").tariff


def test_a_color_is_recognized_by_its_other_states() -> None:
    for state in ("on", "ON", "Pointe mobile", "EJP"):
        context = TariffContext(colors={PEAK: state})
        assert EJP.hourly(PEAK, context)[12] == 0.9, state
    assert EJP.hourly(PEAK, TariffContext(colors={PEAK: "off"}))[12] == 0.2
    assert EJP.hourly(PEAK, TariffContext(colors={PEAK: "inconnu"}))[12] == 0.2  # première


def test_the_ejp_peak_runs_from_7_am_to_1_am() -> None:
    context = TariffContext(colors={PEAK: "on", NEXT: "off"})
    peak, after = EJP.hourly(PEAK, context), EJP.hourly(NEXT, context)
    assert [peak[h] for h in (6, 7, 23)] == [0.2, 0.9, 0.9]
    assert [after[h] for h in (0, 1, 7)] == [0.9, 0.2, 0.2]


def test_states_are_a_set() -> None:
    color = ColorPrices(color="EJP", states=[" on", "Pointe", "", "on"], base_eur_kwh=0.9)
    assert color.states == ["Pointe", "on"]


def test_a_state_twice_is_a_problem() -> None:
    twice = Tariff(
        kind=TariffKind.DAY_COLOR,
        base_eur_kwh=0.2,
        color_entity="sensor.ejp",
        colors=[
            ColorPrices(color="Normal", states=["on"], base_eur_kwh=0.2),
            ColorPrices(color="EJP", states=["ON"], base_eur_kwh=0.9),
        ],
    )
    assert ("color_twice", {}) in problems(twice)
    assert ("color_twice", {}) not in problems(EJP.model_copy(update={"color_entity": "s.e"}))


def test_states_are_saved_and_read_back(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    tariff = EJP.model_copy(update={"color_entity": "sensor.ejp"})
    configuration.save(graph, Configuration(tariff=tariff))
    assert configuration.load(graph).tariff == tariff
