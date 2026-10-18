"""Plans calculés et affectations des tâches, gardés en base (remplacent les ``*.pkl`` de la v1).

Un plan par sorte : ``today`` (le jour, fusionné d'un calcul à l'autre), ``yesterday`` (archivé
à la bascule de minuit, vue Hier), ``tomorrow`` et ``horizon`` (les jours suivants). Contenu au
format de la v1 (sortie du moteur et entrée), en JSON ; les heures, clés d'objets en JSON, sont
relues en entiers.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from wattslot.planning.assignment import Assignment, Previous
from wattslot.planning.plan import Plan

PLAN_KINDS = ("today", "yesterday", "tomorrow", "horizon")


def _hours_back(obj: dict[str, Any]) -> dict[Any, Any]:
    """Clés d'heures relues en entiers (« 12 » → 12)."""
    if obj and all(isinstance(k, str) and k.isdigit() and len(k) <= 2 for k in obj):
        return {int(k): v for k, v in obj.items()}
    return obj


def dumps(content: Any) -> str:
    return json.dumps(content, ensure_ascii=False, default=lambda o: o.isoformat())


def loads(text: str) -> Any:
    return json.loads(text, object_hook=_hours_back)


@dataclass(frozen=True)
class StoredPlan:
    kind: str
    day: date
    content: Any
    computed_at: datetime
    manual: bool
    seconds: float

    @property
    def plan(self) -> Plan:
        """Le plan typé (sans perte : ``plan.to_v1()`` redonne ``content``)."""
        return Plan.from_v1(self.content)


class PlanStore:
    def __init__(self, database: sqlite3.Connection) -> None:
        self._database = database

    def save(self, kind: str, day: date, content: Any, seconds: float, manual: bool) -> None:
        with self._database:
            self._database.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(kind) DO UPDATE SET "
                "day = excluded.day, content = excluded.content, "
                "computed_at = excluded.computed_at, manual = excluded.manual, "
                "seconds = excluded.seconds",
                (
                    kind,
                    day.isoformat(),
                    dumps(content),
                    datetime.now(UTC).isoformat(),
                    int(manual),
                    round(seconds, 2),
                ),
            )

    def load(self, kind: str) -> StoredPlan | None:
        row = self._database.execute(
            "SELECT day, content, computed_at, manual, seconds FROM plans WHERE kind = ?", (kind,)
        ).fetchone()
        if row is None:
            return None
        day, content, computed_at, manual, seconds = row
        return StoredPlan(
            kind,
            date.fromisoformat(day),
            loads(content),
            datetime.fromisoformat(computed_at),
            bool(manual),
            seconds,
        )

    def archive_yesterday(self) -> bool:
        """Le plan du jour devient celui d'hier (bascule de minuit)."""
        current = self.load("today")
        if current is None:
            return False
        with self._database:
            self._database.execute("DELETE FROM plans WHERE kind = 'yesterday'")
            self._database.execute("UPDATE plans SET kind = 'yesterday' WHERE kind = 'today'")
        return True

    def assignments(self, today: date) -> dict[str, Previous]:
        """Affectations précédentes ; une affectation à un jour déjà passé (tâche pas faite)
        perd son jour mais garde sa référence : la tâche est replacée, sa limite ne recule pas."""
        rows = self._database.execute("SELECT uid, day, reference FROM task_assignments")
        found = {}
        for uid, day, reference in rows:
            kept = date.fromisoformat(day) if day and day >= today.isoformat() else None
            found[uid] = Previous(day=kept, reference=date.fromisoformat(reference))
        return found

    def save_assignments(self, assignments: dict[str, Assignment]) -> None:
        with self._database:
            self._database.execute("DELETE FROM task_assignments")
            self._database.executemany(
                "INSERT INTO task_assignments VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        uid,
                        a.day.isoformat(),
                        a.reference.isoformat(),
                        a.task,
                        a.coverage,
                        a.coverage_today,
                    )
                    for uid, a in assignments.items()
                ],
            )
