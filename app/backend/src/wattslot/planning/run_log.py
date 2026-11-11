"""Journal des calculs : ce que chaque calcul du jour a annoncé pour chaque équipement.

L'application ne gardait que le dernier plan fusionné : impossible de dire, après coup, à quelle
heure un appareil avait été annoncé, ni si son heure avait été gardée, déplacée ou replacée
faute de lancement (question posée sur une installation réelle le 11/11/2026, résolue grâce à
l'historique des notifications du téléphone). Une ligne par calcul, gardée ``KEPT_DAYS`` jours et
jointe au rapport anonymisé (``report.py``).

Pour chaque équipement, son départ dans ce calcul, celui du calcul précédent, et ce qui s'est
passé :

- ``new`` : annoncé pour la première fois ;
- ``kept`` : même heure qu'au calcul précédent ;
- ``kept_by_margin`` : même heure, gardée alors qu'un autre départ notait un peu mieux ;
- ``moved`` : heure changée ;
- ``launched`` : cycle réel reconnu, créneau calé sur son démarrage ;
- ``placed_again`` : départ annoncé resté sans activité, replacé (recommandation non suivie) ;
- ``removed`` : annoncé au calcul précédent, plus dans ce plan.
"""

import json
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from wattslot.planning.plan import Plan

KEPT_DAYS = 7


def entry(
    plan: Mapping[str, Any],
    announced: Mapping[str, int],
    launched: set[str] | frozenset[str],
    unfollowed: set[str] | frozenset[str],
) -> dict[str, dict[str, Any]]:
    """Ce que ce calcul dit de chaque équipement. ``plan`` : le plan fusionné du jour ;
    ``announced`` : les départs du calcul précédent ; ``launched`` : cycles réels reconnus ;
    ``unfollowed`` : recommandations non suivies, replacées."""
    slots = {slot.device: slot for slot in Plan.from_v1(dict(plan)).slots}
    found: dict[str, dict[str, Any]] = {}
    for device in sorted(set(slots) | set(announced)):
        slot = slots.get(device)
        start = slot.start_min if slot is not None else None
        previous = announced.get(device)
        reasons = (
            [reason.code for reason in slot.explanation.reasons]
            if slot is not None and slot.explanation is not None
            else []
        )
        if device in unfollowed:
            state = "placed_again"
        elif device in launched or "launched" in reasons:
            state = "launched"
        elif start is None:
            state = "removed"
        elif previous is None:
            state = "new"
        elif start != previous:
            state = "moved"
        else:
            state = "kept_by_margin" if "announced_kept" in reasons else "kept"
        found[device] = {"start_min": start, "previous_min": previous, "state": state}
    return found


def record(
    database: sqlite3.Connection,
    now: datetime,
    day: date,
    manual: bool,
    devices: Mapping[str, Mapping[str, Any]],
) -> None:
    """Note le calcul et retire les lignes de plus de ``KEPT_DAYS`` jours."""
    with database:
        database.execute(
            "INSERT OR REPLACE INTO plan_runs (at, day, manual, devices) VALUES (?, ?, ?, ?)",
            (
                now.isoformat(),
                day.isoformat(),
                int(manual),
                json.dumps(devices, ensure_ascii=False),
            ),
        )
        database.execute(
            "DELETE FROM plan_runs WHERE day < ?",
            ((day - timedelta(days=KEPT_DAYS)).isoformat(),),
        )


def recent(database: sqlite3.Connection, days: int = KEPT_DAYS) -> list[dict[str, Any]]:
    """Calculs des ``days`` derniers jours notés, du plus ancien au plus récent."""
    rows = database.execute("SELECT at, day, manual, devices FROM plan_runs ORDER BY at").fetchall()
    if not rows:
        return []
    first = (date.fromisoformat(str(rows[-1][1])) - timedelta(days=days - 1)).isoformat()
    return [
        {"at": row[0], "day": row[1], "manual": bool(row[2]), "devices": json.loads(row[3])}
        for row in rows
        if str(row[1]) >= first
    ]
