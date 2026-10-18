"""Cartes estimé / mesuré au relevé des vues Aujourd'hui et Hier (lot 5.1, PR 3b).

Reprend le JavaScript de la page de la v1, exécuté jusque-là dans le navigateur :
``majCartesResume`` (estimé et mesuré à l'heure du dernier relevé, et tendance),
``majLignesJournee`` (ligne « Journée » : prévision du premier calcul contre fin de journée
recalculée sur le réel), ``majBandeauMeteo`` (fiabilité de la prévision au relevé) et
``majTendance``, avec leurs fonctions d'appoint (``socEstimeA``, ``socEstimeMaxJusqua``,
``prevuCumule``).
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

TREND_STABLE_PERCENT = 1  # sous 1 % d'écart : stable
ZERO_KWH = 0.005  # prévu nul à l'affichage (0,00 kWh)
WEATHER_RELIABLE = 10  # écart de la production mesurée à la prévision, en %
WEATHER_MODERATE = 25
WEATHER_MIN_KWH = 1  # moins d'1 kWh estimé : trop tôt pour juger

LineKey = Literal[
    "soc", "soc_max", "charge", "discharge", "grid_import", "grid_export", "production"
]
# (couleur inversée : moins est favorable ; prévu nul : « +∞ % » dès qu'il y a du mesuré)
RULES: dict[str, tuple[bool, bool]] = {
    "soc": (False, False),
    "soc_max": (False, False),
    "charge": (False, True),
    "discharge": (True, True),
    "grid_import": (True, False),
    "grid_export": (True, True),
    "production": (False, False),
}
# Clés du résumé de fin de journée de la v1, par ligne de carte.
V1_TOTALS = {
    "charge": "charge_total",
    "discharge": "decharge_total",
    "grid_import": "soutire_total",
    "grid_export": "injecte_total",
    "production": "production_totale",
}


class Trend(BaseModel):
    """Tendance du mesuré par rapport à l'estimé : sens, écart et s'il est favorable."""

    direction: Literal["none", "stable", "up", "down", "infinite"]
    percent: int | None = None
    favorable: bool | None = None  # aucune : neutre


class CardLine(BaseModel):
    key: LineKey
    estimated_kwh: float | None
    measured_kwh: float | None
    estimated_hour: float | None = None  # SoC max : heure (fractionnaire) de l'estimé
    measured_hour: float | None = None  # SoC max : heure du maximum mesuré
    measured_percent: float | None = None  # SoC : pourcentage mesuré
    trend: Trend


class ReadingWeather(BaseModel):
    """Production mesurée comparée à l'estimée, au relevé (journée entière pour Hier)."""

    mode: Literal["reading", "day", "day_last", "no_reading"]
    estimated_kwh: float | None = None
    measured_kwh: float | None = None
    gap_percent: int | None = None
    badge: Literal["reliable", "moderate", "important", "too_early"] | None = None
    initial_at: datetime | None = None  # Hier : heure du premier calcul comparé


class Cards(BaseModel):
    reference_hour: float  # heure du relevé (24 pour Hier)
    at_reading: list[CardLine]
    day: list[CardLine] | None = None  # Aujourd'hui : ligne « Journée »
    weather: ReadingWeather | None = None


def _js_round(value: float) -> int:
    """``Math.round`` (demi vers +∞)."""
    return math.floor(value + 0.5)


def _to_fixed0(value: float) -> int:
    """``toFixed(0)`` (demi loin de zéro)."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def trend(
    estimated: float | None, measured: float | None, inverse: bool, zero_infinite: bool
) -> Trend:
    """Tendance d'une ligne (``majTendance`` de la v1)."""
    if zero_infinite and estimated is not None and estimated < ZERO_KWH and measured is not None:
        if measured >= ZERO_KWH:
            return Trend(direction="infinite", favorable=not inverse)
        return Trend(direction="stable", percent=0)
    if estimated is None or measured is None or estimated == 0:
        return Trend(direction="none")
    gap = (measured - estimated) / abs(estimated) * 100
    if abs(gap) < TREND_STABLE_PERCENT:
        return Trend(direction="stable", percent=0)
    up = gap > 0
    return Trend(
        direction="up" if up else "down",
        percent=_to_fixed0(gap),
        favorable=(not up) if inverse else up,
    )


def cumulated(series: Sequence[float], hour: float) -> float:
    """Prévu cumulé jusqu'à l'heure fractionnaire ``hour`` (``prevuCumule``)."""
    full = math.floor(hour)
    total = sum(series[h] for h in range(min(full, 24)))
    if full < 24:
        total += series[full] * (hour - full)
    return total


def _value(values: Mapping[Any, Any] | None, h: int) -> float | None:
    if not values:
        return None
    found = values.get(h, values.get(str(h)))
    return None if found is None else float(found)


def build_cards(
    state: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    kind: Literal["today", "yesterday"],
    reference_hour: float,
    soc_percent: Sequence[float],
    forecasts: Mapping[str, Sequence[float]],
    summary: Mapping[str, Any],
    initial: Mapping[str, Any] | None,
    battery: Mapping[str, Any] | None,
) -> Cards:
    """Cartes des vues Aujourd'hui et Hier.

    ``soc_percent`` : courbe du SoC affichée (fin de chaque heure) ; ``forecasts`` : séries
    prévues ``charge``, ``discharge``, ``grid_import``, ``grid_export``, ``production`` ;
    ``summary`` : résumé de fin de journée de la courbe affichée (clés de la v1) ;
    ``initial`` : prévision du premier calcul du jour (``prevision_initiale``)."""
    capacity = state.get("capacite_batterie_kwh", 1.0) or 1.0
    initial_kwh = battery.get("soc_initial_kwh", 0.0) if battery else 0.0
    has_actual = bool(actual)
    data = actual or {}
    yesterday_initial = initial if kind == "yesterday" else None

    def kwh(percent: float) -> float:
        return percent / 100 * capacity

    def soc_at(x: float) -> float:
        full = math.floor(x)
        if full >= 24:
            return kwh(soc_percent[23])
        previous = initial_kwh if full == 0 else kwh(soc_percent[full - 1])
        return previous + (kwh(soc_percent[full]) - previous) * (x - full)

    def soc_max_until(x: float) -> tuple[float, float]:
        best_kwh, best_hour = initial_kwh, 0.0
        full = min(math.floor(x), 24)
        for h in range(full):
            value = kwh(soc_percent[h])
            if _js_round(value * 100) > _js_round(best_kwh * 100):
                best_kwh, best_hour = value, h + 1
        if full < 24:
            value = soc_at(x)
            if _js_round(value * 100) > _js_round(best_kwh * 100):
                best_kwh, best_hour = value, x
        return best_kwh, best_hour

    lines: list[CardLine] = []
    anchored: dict[str, Any] = {}

    # SoC : estimé au relevé contre dernier SoC mesuré.
    soc_by_hour = (
        (data.get("soc_pct_fin_heure") or data.get("soc_pct_reel") or {}) if has_actual else {}
    )
    last = next(
        ((h, v) for h in range(23, -1, -1) if (v := _value(soc_by_hour, h)) is not None), None
    )
    soc_estimated = (
        yesterday_initial["soc_final_kwh"] if yesterday_initial else soc_at(reference_hour)
    )
    soc_measured = kwh(last[1]) if last else None
    lines.append(
        CardLine(
            key="soc",
            estimated_kwh=round(soc_estimated, 3),
            measured_kwh=None if soc_measured is None else round(soc_measured, 3),
            measured_percent=last[1] if last else None,
            trend=trend(soc_estimated, soc_measured, *RULES["soc"]),
        )
    )

    # SoC max : maximum estimé jusqu'au relevé contre maximum instantané mesuré.
    if yesterday_initial:
        max_estimated, max_hour = (
            yesterday_initial["soc_max_kwh"],
            float(yesterday_initial["heure_soc_max"]),
        )
    else:
        max_estimated, max_hour = soc_max_until(reference_hour)
    measured_max: tuple[float, float] | None = None  # (pourcentage, heure)
    reading_max = data.get("soc_max_reel") if has_actual else None
    if reading_max and reading_max.get("pct") is not None:
        moment = datetime.fromisoformat(reading_max["heure_iso"])
        measured_max = (reading_max["pct"], moment.hour + moment.minute / 60)
    else:
        values = [(h, v) for h in range(24) if (v := _value(soc_by_hour, h)) is not None]
        if values:
            h, v = max(values, key=lambda p: p[1])
            measured_max = (v, float(h))
    midnight = data.get("soc_pct_minuit") if has_actual else None
    if midnight is not None and (measured_max is None or midnight >= measured_max[0]):
        measured_max = (midnight, 0.0)
    measured_max_kwh = kwh(measured_max[0]) if measured_max else None
    if measured_max and kind != "yesterday":
        anchored.update(
            soc_max_kwh=measured_max_kwh, soc_max_pct=measured_max[0], heure_soc_max=measured_max[1]
        )
        for h in range(math.floor(reference_hour), 24):
            value = kwh(soc_percent[h])
            if value > anchored["soc_max_kwh"]:
                anchored.update(
                    soc_max_kwh=value, soc_max_pct=soc_percent[h], heure_soc_max=float(h + 1)
                )
    lines.append(
        CardLine(
            key="soc_max",
            estimated_kwh=round(max_estimated, 3),
            measured_kwh=None if measured_max_kwh is None else round(measured_max_kwh, 3),
            estimated_hour=max_hour,
            measured_hour=measured_max[1] if measured_max else None,
            measured_percent=measured_max[0] if measured_max else None,
            trend=trend(max_estimated, measured_max_kwh, *RULES["soc_max"]),
        )
    )

    # Totaux du jour : cumulés jusqu'au relevé.
    battery_segments = data.get("batterie_reelle_segments") or [] if has_actual else []

    def segments_total(action: str) -> float:
        return float(
            sum(s.get("energie_kwh") or 0 for s in battery_segments if s.get("action") == action)
        )

    def dict_total(key: str) -> float:
        return float(sum((v or 0) for v in (data.get(key) or {}).values()))

    measured_totals = {
        "charge": segments_total("charge"),
        "discharge": segments_total("decharge"),
        "grid_import": dict_total("reseau_reel_soutire_horaire"),
        "grid_export": dict_total("reseau_reel_injecte_horaire"),
        "production": dict_total("production_reelle_horaire"),
    }
    weather: ReadingWeather | None = None
    for key, v1_key in V1_TOTALS.items():
        series = forecasts[key]
        measured = measured_totals[key] if has_actual else None
        if measured is not None and kind != "yesterday":
            anchored[v1_key] = measured + cumulated(series, 24) - cumulated(series, reference_hour)
        estimated = (
            yesterday_initial[v1_key] if yesterday_initial else cumulated(series, reference_hour)
        )
        lines.append(
            CardLine(
                key=key,  # type: ignore[arg-type]
                estimated_kwh=round(estimated, 3),
                measured_kwh=None if measured is None else round(measured, 3),
                trend=trend(estimated, measured, *RULES[key]),
            )
        )
        if key == "production":
            weather = reading_weather(kind, estimated, measured, yesterday_initial)

    day = None
    if kind == "today":
        day = day_lines(initial, {**summary, **anchored})
    return Cards(
        reference_hour=round(reference_hour, 4), at_reading=lines, day=day, weather=weather
    )


def reading_weather(
    kind: str, estimated: float, measured: float | None, initial: Mapping[str, Any] | None
) -> ReadingWeather:
    """Fiabilité de la prévision au relevé (``majBandeauMeteo``)."""
    if measured is None:
        return ReadingWeather(mode="no_reading" if kind != "yesterday" else "day_last")
    gap = None
    badge = "too_early"
    if estimated >= WEATHER_MIN_KWH:
        gap = _js_round((measured - estimated) / estimated * 100)
        size = abs(gap)
        badge = (
            "reliable"
            if size <= WEATHER_RELIABLE
            else "moderate"
            if size <= WEATHER_MODERATE
            else "important"
        )
    initial_at = None
    if kind != "yesterday":
        mode = "reading"
    elif initial and initial.get("heure_iso"):
        mode, initial_at = "day", datetime.fromisoformat(initial["heure_iso"])
    else:
        mode = "day_last"
    return ReadingWeather(
        mode=mode,  # type: ignore[arg-type]
        estimated_kwh=round(estimated, 3),
        measured_kwh=round(measured, 3),
        gap_percent=gap,
        badge=badge,  # type: ignore[arg-type]
        initial_at=initial_at,
    )


def day_lines(initial: Mapping[str, Any] | None, final: Mapping[str, Any]) -> list[CardLine]:
    """Ligne « Journée » (``majLignesJournee``) : prévision du premier calcul du jour contre fin
    de journée recalculée et ancrée sur le réel."""

    def value(source: Mapping[str, Any] | None, key: str) -> float | None:
        return None if source is None or source.get(key) is None else float(source[key])

    found = [
        CardLine(
            key="soc",
            estimated_kwh=value(initial, "soc_final_kwh"),
            measured_kwh=value(final, "soc_final_kwh"),
            measured_percent=value(final, "soc_final_pct"),
            trend=trend(
                value(initial, "soc_final_kwh"), value(final, "soc_final_kwh"), False, False
            ),
        ),
        CardLine(
            key="soc_max",
            estimated_kwh=value(initial, "soc_max_kwh"),
            measured_kwh=value(final, "soc_max_kwh"),
            estimated_hour=value(initial, "heure_soc_max"),
            measured_hour=value(final, "heure_soc_max"),
            measured_percent=value(final, "soc_max_pct"),
            trend=trend(value(initial, "soc_max_kwh"), value(final, "soc_max_kwh"), False, False),
        ),
    ]
    for key, v1_key in V1_TOTALS.items():
        found.append(
            CardLine(
                key=key,  # type: ignore[arg-type]
                estimated_kwh=value(initial, v1_key),
                measured_kwh=value(final, v1_key),
                trend=trend(value(initial, v1_key), value(final, v1_key), *RULES[key]),
            )
        )
    return found
