"""Explications du plan (lot 3.7).

Chaque élément du plan reçoit une explication **structurée** (codes et paramètres, sans texte) :

- ses **raisons** : objectif en jeu, part de son énergie couverte par le surplus solaire, heures
  les moins chères, « après la fin de », contraintes respectées, démarrage réel, échéance, durée
  minimale, autoconsommation et plancher de la batterie, charge complète due ;
- pour un cycle placé, l'**alternative** : le meilleur autre départ permis selon l'objectif, avec
  ce qu'il changerait au coût et au soutirage, le reste du plan inchangé (batterie rejouée).

Le texte (``justification``, recommandation) en est tiré dans la langue voulue, à partir des
catalogues ``planning/locales/{fr,en}.json`` : un code sans texte est une erreur, pas un trou.
"""

import json
import math
from collections.abc import Callable, Mapping
from functools import cache
from pathlib import Path
from typing import Any

from wattslot import currency
from wattslot.languages import language_of, number
from wattslot.planning.plan import (
    Alternative,
    BatteryPlan,
    Explanation,
    Indicators,
    Reason,
    RuntimePlan,
    Slot,
)
from wattslot.planning.plan import Plan as DayPlan
from wattslot.planning.problem import Problem, Task
from wattslot.time_constraints import labels

LOCALES = Path(__file__).parent / "locales"
PRICE_SPREAD_EUR = 0.005  # en dessous, toutes les heures coûtent pareil : pas d'« heures creuses »
ALTERNATIVES = 3  # autres départs proposés au plus, par cycle

# Départs (tâche → minutes) → indicateurs du plan ainsi modifié ; indicateurs → note (plus bas :
# meilleur) selon l'objectif.
Evaluate = Callable[[dict[str, int]], Indicators]
Score = Callable[[Indicators], float]


# --- Raisons ---------------------------------------------------------------------------------


def solar_percent(hourly: Mapping[int, float], problem: Problem, load: Mapping[int, float]) -> int:
    """Part de l'énergie de l'élément couverte par le surplus solaire de ses heures, avant la
    batterie, sa propre consommation mise à part."""
    total = sum(hourly.values())
    if total <= 0:
        return 0
    covered = 0.0
    for hour, kwh in hourly.items():
        surplus = problem.net_kwh.get(hour, 0.0) - (load.get(hour, 0.0) - kwh)
        covered += min(kwh, max(0.0, surplus))
    return round(100 * covered / total)


def _cheap(hourly: Mapping[int, float], problem: Problem) -> Reason | None:
    prices = problem.prices_eur_kwh
    hours = [h for h, kwh in hourly.items() if kwh > 0 and h in prices]
    if not hours or max(prices.values()) - min(prices.values()) < PRICE_SPREAD_EUR:
        return None
    lowest = min(prices[h] for h in problem.hours)
    if all(abs(prices[h] - lowest) < 1e-9 for h in hours):
        return Reason(code="cheap_hours", params={"price": round(lowest, 4)})
    return None


def _common(
    name: str,
    hourly: Mapping[int, float],
    problem: Problem,
    load: Mapping[int, float],
    objective: str,
) -> list[Reason]:
    reasons = [Reason(code="objective", params={"objective": objective})]
    solar = solar_percent(hourly, problem, load)
    if solar > 0:
        reasons.append(Reason(code="solar_share", params={"percent": solar}))
    cheap = _cheap(hourly, problem)
    if cheap is not None:
        reasons.append(cheap)
    constraints = problem.constraints.get(name, ())
    if constraints:
        reasons.append(Reason(code="constraints", params={"constraints": labels(constraints)}))
    return reasons


def _alternatives(
    task: Task,
    starts: dict[str, int],
    problem: Problem,
    base: Indicators,
    evaluate: Evaluate,
    score: Score,
) -> tuple[list[Alternative], bool]:
    """Meilleurs autres départs permis du cycle (contraintes dures, ordre avec les cycles liés),
    le reste du plan inchangé, et si le meilleur d'entre eux note mieux que le départ du plan.
    Le départ choisi par l'utilisateur n'en retire aucun."""
    by_key = {t.key: t for t in problem.tasks}
    parent = by_key.get(task.depends_on or "")
    earliest = task.earliest_min
    if parent is not None and parent.name in starts:
        earliest = max(earliest, starts[parent.name] + parent.slot_min)
    children = [
        starts[t.name] for t in problem.tasks if t.depends_on == task.key and t.name in starts
    ]
    latest_end = min(children) if children else math.inf
    found: list[tuple[float, int, Indicators]] = []
    for start in task.candidates(earliest, chosen=False):
        if start == starts[task.name] or start + task.slot_min > latest_end:
            continue
        if problem.hard_blocks(task.name, start, start + task.slot_min):
            continue
        indicators = evaluate({**starts, task.name: start})
        found.append((score(indicators), start, indicators))
    found.sort(key=lambda item: (item[0], item[1]))
    alternatives = [
        Alternative(
            start_min=start,
            cost_eur_delta=round(indicators.cost_eur - base.cost_eur, 3),
            import_kwh_delta=round(indicators.import_kwh - base.import_kwh, 3),
        )
        for _, start, indicators in found[:ALTERNATIVES]
    ]
    better = bool(found) and found[0][0] < score(base) - 1e-6
    return alternatives, better


def explain(
    problem: Problem,
    day: DayPlan,
    starts: Mapping[str, int],
    load: Mapping[int, float],
    objective: str,
    evaluate: Evaluate,
    score: Score,
) -> DayPlan:
    """Plan avec l'explication de chaque élément ; sa ``justification`` en est le texte
    français."""
    tasks = {t.name: t for t in problem.tasks}
    by_key = {t.key: t for t in problem.tasks}
    launched = {c.name: c for c in problem.launched}
    needs = {n.name: n for n in problem.needs}
    runtimes = {r.name: r for r in problem.runtimes}
    base = day.indicators
    items = []
    for item in day.items:
        explanation = Explanation()
        if isinstance(item, BatteryPlan):
            battery = problem.battery
            reasons = [
                Reason(
                    code="self_consumption_mode",
                    params={"start": battery.active_from, "end": battery.active_to},
                )
            ]
            if battery.capacity_kwh > 0:
                floor = round(100 * battery.floor_kwh / battery.capacity_kwh)
                reasons.append(Reason(code="floor", params={"percent": floor}))
            if battery.full_priority:
                reasons.append(Reason(code="full_charge_due"))
            explanation = Explanation(reasons=reasons)
        elif isinstance(item, RuntimePlan):
            model = runtimes.get(item.device)
            running = {
                h: 1.0
                for s in item.segments
                if s.mode != "off"
                for h in range(s.start_hour, s.end_hour)
            }
            reasons = [Reason(code="objective", params={"objective": objective})]
            if model is not None and model.skipped:
                reasons.append(Reason(code="skipped_full_charge"))
            elif model is not None and model.min_hours > 0:
                reasons.append(Reason(code="minimum_hours", params={"hours": model.min_hours}))
            surplus = sum(1 for h in running if problem.net_kwh.get(h, 0.0) > 0)
            if surplus:
                reasons.append(Reason(code="solar_hours", params={"hours": surplus}))
            if problem.constraints.get(item.device):
                constraints = labels(problem.constraints[item.device])
                reasons.append(Reason(code="constraints", params={"constraints": constraints}))
            explanation = Explanation(reasons=reasons)
        elif isinstance(item, Slot) and item.device in launched:
            moment = launched[item.device].start
            explanation = Explanation(
                reasons=[Reason(code="launched", params={"time": f"{moment:%H}h{moment:%M}"})]
            )
        elif isinstance(item, Slot) and item.hourly_kwh is not None and item.device in needs:
            need = needs[item.device]
            reasons = [
                Reason(
                    code="deadline",
                    params={"energy_kwh": need.energy_kwh, "hour": need.deadline_hour},
                ),
                *_common(item.device, item.hourly_kwh, problem, load, objective),
            ]
            explanation = Explanation(reasons=reasons)
        elif isinstance(item, Slot) and item.device in tasks and item.device in starts:
            task = tasks[item.device]
            hourly = task.hourly_kwh(starts[task.name])
            reasons = _common(task.name, hourly, problem, load, objective)
            parent = by_key.get(task.depends_on or "")
            if parent is not None:
                reasons.append(Reason(code="after", params={"device": parent.name}))
            alternatives, better = (
                _alternatives(task, dict(starts), problem, base, evaluate, score)
                if base is not None
                else ([], False)
            )
            chosen = task.chosen_min is not None and starts[task.name] == task.chosen_min
            if chosen:
                # Départ choisi par l'utilisateur : ni objectif ni « batterie d'abord ».
                reasons = [Reason(code="chosen")] + [r for r in reasons if r.code != "objective"]
            elif better and problem.battery.full_priority:
                # Un autre départ coûterait moins : le surplus va d'abord à la charge complète.
                reasons = [Reason(code="full_charge_first")] + [
                    r for r in reasons if r.code != "objective"
                ]
            explanation = Explanation(
                reasons=reasons,
                alternative=alternatives[0] if alternatives else None,
                alternatives=alternatives,
                chosen=chosen,
            )
        if explanation.reasons:
            item = item.model_copy(
                update={"explanation": explanation, "justification": render(explanation, "fr")}
            )
        items.append(item)
    return day.model_copy(update={"items": items})


# --- Texte -----------------------------------------------------------------------------------


@cache
def catalog(lang: str) -> dict[str, str]:
    """Textes d'une langue des six (lot 5.7), le français pour une langue inconnue."""
    found: dict[str, str] = json.loads(
        (LOCALES / f"{language_of(lang)}.json").read_text(encoding="utf-8")
    )
    return found


def _param(name: str, value: Any, lang: str) -> str:
    if name == "objective":
        return catalog(lang)[f"objective.{value}"]
    if name == "price":
        return currency.per_kwh(float(value), lang)
    if name == "energy_kwh":
        return number(float(value), lang, 1)
    return str(value)


def render(explanation: Explanation, lang: str = "fr", without: tuple[str, ...] = ()) -> str:
    """Texte de l'explication, sans les raisons de codes ``without`` ; ``KeyError`` pour un
    code sans texte dans la langue."""
    texts = catalog(lang)
    sentences = [
        texts[f"reason.{r.code}"].format(**{k: _param(k, v, lang) for k, v in r.params.items()})
        for r in explanation.reasons
        if r.code not in without
    ]
    alternative = explanation.alternative
    if alternative is not None:
        hours, minutes = divmod(alternative.start_min, 60)
        same = abs(alternative.cost_eur_delta) < 0.005 and abs(alternative.import_kwh_delta) < 0.05
        sentences.append(
            texts["alternative_same" if same else "alternative"].format(
                time=f"{hours}h{minutes:02d}" if minutes else f"{hours}h",
                cost=currency.amount(alternative.cost_eur_delta, lang, signed=True),
                grid=number(alternative.import_kwh_delta, lang, 1, signed=True),
            )
        )
    return " ".join(sentences)
