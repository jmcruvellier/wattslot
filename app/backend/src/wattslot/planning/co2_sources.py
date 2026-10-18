"""Intensité carbone du réseau lue dans HA (lot 3.6) : objectif CO₂ et indicateur du plan.

Entité choisie dans l'objectif de la configuration (Electricity Maps, CO2 Signal…), en g/kWh :

- **prévision** : toute liste horodatée de ses attributs (``forecast`` et autres, mêmes formats
  que les prix dynamiques, plus ``datetime`` / ``carbon_intensity``), moyennée par heure locale ;
- sinon sa **valeur courante**, pour toutes les heures : le plan est alors celui de l'autonomie
  (le moins de soutirage), seul l'indicateur en kg de CO₂ s'y ajoute.

Un profil moyen tiré de l'historique de l'entité est remis à plus tard.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from wattslot.planning.tariff_sources import (
    START_KEYS,
    UNKNOWN,
    VALUE_KEYS,
    hourly_prices,
    price_points,
)

CO2_START_KEYS = (*START_KEYS, "datetime")
CO2_VALUE_KEYS = (*VALUE_KEYS, "carbon_intensity", "intensity", "co2")


@dataclass(frozen=True)
class Co2Context:
    by_day: Mapping[date, Mapping[int, float]] = field(default_factory=dict)  # g/kWh
    current: float | None = None  # valeur courante de l'entité

    def hourly(self, day: date) -> dict[int, float]:
        """g/kWh de chaque heure du jour ; vide sans aucune donnée."""
        known = self.by_day.get(day, {})
        if self.current is None and not known:
            return {}
        fallback = self.current if self.current is not None else sum(known.values()) / len(known)
        return {h: known.get(h, fallback) for h in range(24)}


def co2_context(
    states: Sequence[dict[str, Any]], entity_id: str | None, zone: ZoneInfo
) -> Co2Context:
    state = next((s for s in states if entity_id and s.get("entity_id") == entity_id), None)
    if state is None:
        return Co2Context()
    raw = str(state.get("state", "")).strip()
    try:
        current = float(raw) if raw.casefold() not in UNKNOWN else None
    except ValueError:
        current = None
    points = price_points(state.get("attributes") or {}, CO2_START_KEYS, CO2_VALUE_KEYS)
    return Co2Context(by_day=hourly_prices(points, 1.0, zone), current=current)
