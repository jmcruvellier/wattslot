"""Ce que HA apprend du tarif (lot 3.2) : couleur des jours (Tempo), prix dynamiques connus.

Lu une fois par calcul, sur les états de HA déjà lus pour les prévisions (``Forecasts``).

- **Couleur** : état de l'entité de couleur du jour et, s'il y en a une, de celle du lendemain ;
  un état inconnu (``unknown``, ``unavailable``) ne donne pas de couleur.
- **Prix dynamiques** : toute liste de prix horodatés dans les attributs de l'entité, quel que
  soit le format de l'intégration : Nordpool (``raw_today``, ``raw_tomorrow`` : ``start``,
  ``value``), ENTSO-e (``prices`` : ``time``, ``price``), Tibber (``startsAt``, ``total``),
  Octopus (``valid_from``, ``value_inc_vat``)… Prix multipliés par ``price_factor`` (unité de
  l'entité vers €/kWh), moyennés par heure locale (quarts d'heure compris).
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from wattslot.tariff import Tariff, TariffContext, TariffKind

START_KEYS = ("start", "startsAt", "starts_at", "start_time", "time", "from", "valid_from")
VALUE_KEYS = ("value", "price", "total", "value_inc_vat", "price_per_kwh", "price_eur_kwh")
UNKNOWN = {"unknown", "unavailable", "none", ""}


def _state(states: Sequence[dict[str, Any]], entity_id: str | None) -> dict[str, Any] | None:
    if not entity_id:
        return None
    return next((s for s in states if s.get("entity_id") == entity_id), None)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def price_points(
    attributes: dict[str, Any],
    start_keys: Sequence[str] = START_KEYS,
    value_keys: Sequence[str] = VALUE_KEYS,
) -> list[tuple[datetime, float]]:
    """(instant, valeur) de toutes les listes horodatées des attributs (prix, ou intensité
    carbone avec d'autres clés)."""
    found: list[tuple[datetime, float]] = []
    for value in attributes.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            start = next((_moment(item[k]) for k in start_keys if k in item), None)
            price = next((_number(item[k]) for k in value_keys if k in item), None)
            if start is not None and price is not None:
                found.append((start, price))
    return found


def hourly_prices(
    points: Sequence[tuple[datetime, float]], factor: float, zone: ZoneInfo
) -> dict[date, dict[int, float]]:
    """Prix moyen par jour et heure locale (€/kWh)."""
    sums: dict[tuple[date, int], list[float]] = defaultdict(list)
    for moment, price in dict(points).items():  # un instant compté une fois
        local = moment.astimezone(zone)
        sums[(local.date(), local.hour)].append(price * factor)
    found: dict[date, dict[int, float]] = defaultdict(dict)
    for (day, hour), prices in sums.items():
        found[day][hour] = round(sum(prices) / len(prices), 6)
    return dict(found)


def tariff_context(
    tariff: Tariff, states: Sequence[dict[str, Any]], today: date, zone: ZoneInfo
) -> TariffContext:
    context = TariffContext()
    if tariff.kind is TariffKind.DAY_COLOR:
        for day, entity_id in (
            (today, tariff.color_entity),
            (today + timedelta(days=1), tariff.color_tomorrow_entity),
        ):
            state = _state(states, entity_id)
            color = str(state.get("state", "")) if state else ""
            if color.strip().casefold() not in UNKNOWN:
                context.colors[day] = color
    if tariff.kind is TariffKind.DYNAMIC:
        state = _state(states, tariff.price_entity)
        if state:
            points = price_points(state.get("attributes") or {})
            context.prices = hourly_prices(points, tariff.price_factor, zone)
    state = _state(states, tariff.export_entity)
    if state:
        points = price_points(state.get("attributes") or {})
        context.export = hourly_prices(points, tariff.price_factor, zone)
    return context


def needs_states(tariff: Tariff) -> bool:
    return bool(tariff.kind in (TariffKind.DAY_COLOR, TariffKind.DYNAMIC) or tariff.export_entity)
