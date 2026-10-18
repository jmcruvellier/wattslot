"""Explications du plan (lot 3.7) : chaque élément du plan de la maison de référence a la sienne,
en français et en anglais ; alternative chiffrée des cycles."""

from pathlib import Path

import pytest

from tests.v1_oracle import STATES, load
from wattslot import profiles
from wattslot.languages import LANGUAGES
from wattslot.planning.assemble import configured
from wattslot.planning.engine import Objective, load_kwh, plan_day
from wattslot.planning.explain import catalog, render, solar_percent
from wattslot.planning.inputs import from_v1
from wattslot.planning.plan import Alternative, Explanation, Reason, Slot
from wattslot.planning.problem import from_input

REFERENCE = profiles.load("reference")
IDS = [p.stem for p in STATES]


def test_the_catalogs_have_the_same_texts() -> None:
    assert set(catalog("fr")) == set(catalog("en"))


@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_every_item_of_the_reference_plan_is_explained(path: Path) -> None:
    state, _ = load(path)
    data = configured(from_v1(state), REFERENCE.home, REFERENCE.configuration)

    day = plan_day(from_input(data)).day

    for item in day.items:
        assert item.explanation is not None and item.explanation.reasons, item.device
        texts = {lang: render(item.explanation, lang) for lang in LANGUAGES}
        assert all(texts.values()) and texts["fr"] != texts["en"]
        assert item.justification == texts["fr"]


@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_no_alternative_is_better_for_the_cost_objective(path: Path) -> None:
    state, _ = load(path)

    day = plan_day(from_input(from_v1(state)), Objective.COST).day

    for slot in day.items:
        if isinstance(slot, Slot) and slot.explanation and slot.explanation.alternative:
            assert slot.explanation.alternative.cost_eur_delta >= -0.01, slot.device
            assert slot.explanation.alternative.start_min != slot.start_min


def test_a_cycle_explains_its_solar_share_and_its_order() -> None:
    """Raisons fidèles au départ retenu, quel qu'il soit (à coût égal, le solveur peut en
    choisir un autre selon la plateforme)."""
    state, _ = load(STATES[11])  # lave-linge et sèche-linge à placer, journée ensoleillée
    problem = from_input(from_v1(state))

    result = plan_day(problem)

    consumption = load_kwh(problem, result.plan)
    tasks = {t.name: t for t in problem.tasks}
    explained = {
        i.device: i.explanation.reasons
        for i in result.day.items
        if isinstance(i, Slot) and i.explanation is not None and i.device in tasks
    }
    assert len(explained) == 3  # chauffe-eau, lave-linge, sèche-linge
    for name, reasons in explained.items():
        codes = [r.code for r in reasons]
        hourly = tasks[name].hourly_kwh(result.plan.starts[name])
        solar = solar_percent(hourly, problem, consumption)
        assert codes[0] == "objective"
        assert ("solar_share" in codes) == (solar > 0), name
        if solar:
            share = next(r for r in reasons if r.code == "solar_share")
            assert share.params == {"percent": solar}
        assert ("after" in codes) == (tasks[name].depends_on is not None), name


def test_rendering_in_each_language() -> None:
    explanation = Explanation(
        reasons=[
            Reason(code="objective", params={"objective": "cost"}),
            Reason(code="cheap_hours", params={"price": 0.138252}),
        ],
        alternative=Alternative(start_min=600, cost_eur_delta=0.18, import_kwh_delta=0.6),
    )

    assert render(explanation, "fr") == (
        "Placé pour le coût le plus bas. Aux heures les moins chères (0,138 €/kWh). "
        "Autre départ possible à 10h : +0,18 € et +0,6 kWh soutirés par rapport à ce plan."
    )
    assert render(explanation, "en").endswith(
        "+0.18 € and +0.6 kWh imported compared with this plan."
    )
    same = Alternative(start_min=600, cost_eur_delta=0.001, import_kwh_delta=0.0)
    assert "aussi bon" in render(explanation.model_copy(update={"alternative": same}), "fr")
    with pytest.raises(KeyError):
        render(Explanation(reasons=[Reason(code="unknown")]), "fr")


def test_the_far_horizon_days_are_not_explained() -> None:
    state, _ = load(STATES[11])

    day = plan_day(from_input(from_v1(state)), explained=False).day

    assert all(item.explanation is None for item in day.items)
