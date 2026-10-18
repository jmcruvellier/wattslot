"""Reprise de l'historique de HA en agrégats (lot 1.3, 2/2).

Pour chaque entité suivie, une seule fois (puis pour chaque entité ajoutée à la maison), les
statistiques du recorder de HA (``recorder/statistics_during_period``) deviennent des agrégats :

- statistiques horaires → agrégats à l'heure, aussi loin qu'elles remontent (HA ne les purge pas) ;
- statistiques à 5 minutes → agrégats au quart d'heure, sur ce que la purge du recorder a laissé
  (``purge_keep_days``, 10 jours par défaut) : rien à régler, la reprise prend ce que HA renvoie.

Compteurs : ``change`` (énergie de la période, remises à zéro gérées par HA). Autres mesures :
``mean`` et ``max``. HA convertit lui-même les unités (``units``) : kWh et W, comme le brut.

Seules les entités qui ont un ``state_class`` ont des statistiques ; les autres sont signalées.
Les périodes déjà calculées sur le brut, ou pas encore closes pour l'agrégation, ne sont pas
reprises : un agrégat n'a jamais deux valeurs.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from wattslot.home_assistant import HomeAssistantClient

SINCE = datetime(2000, 1, 1, tzinfo=UTC)  # avant toute statistique : HA renvoie ce qu'il a
STATISTICS_PERIODS = {"PT15M": "5minute", "PT1H": "hour"}
UNITS = {"energy": "kWh", "power": "W"}


def statistic_time(value: Any) -> datetime:
    """Heure d'une statistique : millisecondes depuis l'époque (HA récent) ou texte ISO."""
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return datetime.fromisoformat(str(value)).astimezone(UTC)


async def statistics(
    client: HomeAssistantClient, entity_id: str, period: str, end: datetime, counter: bool
) -> list[dict[str, Any]]:
    result = await client.command(
        "recorder/statistics_during_period",
        start_time=SINCE.isoformat(),
        end_time=end.isoformat(),
        statistic_ids=[entity_id],
        period=STATISTICS_PERIODS[period],
        units=UNITS,
        types=["change"] if counter else ["mean", "max"],
    )
    rows = (result or {}).get(entity_id) or []
    return [row for row in rows if isinstance(row, dict) and row.get("start") is not None]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN écarté


def group(
    rows: list[dict[str, Any]],
    counter: bool,
    period_of: Callable[[datetime], datetime],
    before: datetime,
) -> dict[datetime, tuple[float | None, float | None, float | None]]:
    """Statistiques regroupées par période (énergie, moyenne, maximum), avant ``before``.

    Trois statistiques à 5 minutes font un quart d'heure : énergies additionnées, moyennes
    moyennées, maximum des maximums.
    """
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        start = statistic_time(row["start"])
        if start < before:
            buckets.setdefault(period_of(start), []).append(row)
    grouped: dict[datetime, tuple[float | None, float | None, float | None]] = {}
    for start, items in buckets.items():
        if counter:
            changes = [c for c in (_number(r.get("change")) for r in items) if c is not None]
            if changes:
                grouped[start] = (sum(changes), None, None)
            continue
        means = [m for m in (_number(r.get("mean")) for r in items) if m is not None]
        maxes = [m for m in (_number(r.get("max")) for r in items) if m is not None]
        if means:
            grouped[start] = (None, sum(means) / len(means), max(maxes or means))
    return grouped
