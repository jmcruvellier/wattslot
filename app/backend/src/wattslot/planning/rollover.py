"""Bascule de minuit : moment où le calcul du jour repasse pour le nouveau jour.

Réécriture de ``bascule_jour.py`` (v1), dans le fuseau de HA au lieu de
``Europe/Paris``. Sans elle, le plan du jour resterait celui de la veille jusqu'au premier
calcul horaire. Une minute après minuit : le relevé du nouveau jour a au moins une minute de
données, et le calcul de 23 h 59 a le temps de finir.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ROLLOVER_AT = time(0, 1)


def next_rollover(now: datetime, zone: ZoneInfo) -> datetime:
    """Prochaine bascule (0 h 01, heure locale) strictement après ``now``."""
    local = now.astimezone(zone)
    target = datetime.combine(local.date(), ROLLOVER_AT, tzinfo=zone)
    if target <= local:
        target = datetime.combine(local.date() + timedelta(days=1), ROLLOVER_AT, tzinfo=zone)
    return target


def seconds_until(target: datetime, now: datetime) -> float:
    """Durée réelle jusqu'à ``target`` (sur les instants : juste aussi les nuits de changement
    d'heure, contrairement à une soustraction en heure murale)."""
    return max(0.0, target.timestamp() - now.timestamp())
