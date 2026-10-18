"""Échéances des tâches récurrentes sur l'horizon de planification.

Réécriture de ``recurrences.py`` (v1), son oracle dans les tests. La liste de tâches de
HA ne porte que la prochaine échéance d'une tâche récurrente et sa règle (RFC 5545) : les
échéances suivantes s'en déduisent (échéance, échéance + intervalle…).

Règles gérées : ``FREQ=DAILY`` ou ``WEEKLY``, ``INTERVAL``, ``BYDAY`` (``WEEKLY`` seulement) et
``UNTIL``. Toute autre règle n'est pas devinée : seule l'échéance est retenue, et la tâche est
signalée pour un avertissement. Les occurrences partent toujours de l'échéance, jamais d'une
date antérieure : une tâche en retard garde ses occurrences futures.
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta

from wattslot.planning.inputs import TaskRequest

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
SUPPORTED = {"FREQ", "INTERVAL", "BYDAY", "UNTIL"}


class UnsupportedRule(ValueError):
    """Règle de récurrence hors du sous-ensemble géré."""


@dataclass(frozen=True)
class Rule:
    weekly: bool
    interval: int
    weekdays: frozenset[int] | None
    until: date | None


def parse_rule(text: str) -> Rule:
    properties: dict[str, str] = {}
    for piece in text.strip().removeprefix("RRULE:").split(";"):
        if not piece:
            continue
        key, _, value = piece.partition("=")
        properties[key.strip().upper()] = value.strip().upper()
    unknown = set(properties) - SUPPORTED
    if unknown:
        raise UnsupportedRule(f"propriété(s) non gérée(s) : {', '.join(sorted(unknown))}")
    if properties.get("FREQ") not in ("DAILY", "WEEKLY"):
        raise UnsupportedRule(f"FREQ={properties.get('FREQ')!r} non gérée")
    try:
        interval = int(properties.get("INTERVAL", "1"))
    except ValueError:
        raise UnsupportedRule(f"INTERVAL={properties['INTERVAL']!r} invalide") from None
    if interval < 1:
        raise UnsupportedRule(f"INTERVAL={interval} invalide")
    weekdays = None
    if "BYDAY" in properties:
        if properties["FREQ"] != "WEEKLY":
            raise UnsupportedRule("BYDAY n'est géré qu'avec FREQ=WEEKLY")
        try:
            weekdays = frozenset(WEEKDAYS[d] for d in properties["BYDAY"].split(","))
        except KeyError:
            raise UnsupportedRule(f"BYDAY={properties['BYDAY']!r} non géré") from None
    until = None
    if "UNTIL" in properties:
        raw = properties["UNTIL"]
        try:
            until = date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
        except ValueError:
            raise UnsupportedRule(f"UNTIL={raw!r} invalide") from None
    return Rule(properties["FREQ"] == "WEEKLY", interval, weekdays, until)


def occurrences(due: date, rule_text: str, first: date, last: date) -> list[date]:
    """Échéances de la tâche dans [first, last], à partir de ``due``."""
    rule = parse_rule(rule_text)
    last = min(last, rule.until) if rule.until else last
    if not rule.weekly:
        step = timedelta(days=rule.interval)
        current = due
        if first > due:
            current = due + step * (-(-(first - due).days // rule.interval))
        found = []
        while current <= last:
            found.append(current)
            current += step
        return found
    # Semaines comptées depuis celle de l'échéance, une sur INTERVAL ; sans BYDAY, le jour
    # de la semaine de l'échéance.
    weekdays = rule.weekdays if rule.weekdays is not None else frozenset({due.weekday()})
    due_monday = due - timedelta(days=due.weekday())
    found, current = [], max(first, due)
    while current <= last:
        week = (current - due_monday).days // 7
        if week % rule.interval == 0 and current.weekday() in weekdays:
            found.append(current)
        current += timedelta(days=1)
    return found


def tasks_of_day(tasks: list[TaskRequest], day: date) -> tuple[list[TaskRequest], list[str]]:
    """(tâches datées qui concernent ``day``, échéance réécrite à ce jour ; noms des tâches
    récurrentes dont la règle n'est pas gérée). Une tâche sans échéance est ignorée."""
    kept: list[TaskRequest] = []
    unsupported: list[str] = []
    for task in tasks:
        if task.due is None:
            continue
        concerned = task.due == day
        if task.rule:
            try:
                concerned = day in occurrences(task.due, task.rule, day, day)
            except UnsupportedRule:
                unsupported.append(task.name)
        if concerned:
            kept.append(replace(task, due=day))
    return kept, unsupported
