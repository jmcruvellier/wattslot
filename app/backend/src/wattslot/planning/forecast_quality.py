"""Qualité des prévisions d'un plan : à quel point se fier à la production et à la consommation
prévues, d'après les données dont le calcul disposait.

Deux temps :

- au calcul (``plan_state``), ``stored`` garde ce que l'entrée sait de ses données : nombre de
  jours comparables derrière la consommation habituelle de chaque heure (``past.baseline`` :
  les 6 derniers mêmes jours de la semaine, au moins 3 jours par heure), régularité de la
  consommation d'un jour à l'autre, prévision solaire de repli, cycles sans profil appris ;
- à l'affichage (``assess``), ces données, l'éloignement du jour (une prévision météo à 5 jours
  est moins sûre qu'à 1 jour) et la reprise de l'historique de HA donnent des critères notés
  bon, moyen ou faible, et une note d'ensemble.

L'interface rédige les textes (critère, niveau et paramètres) ; un plan calculé avant ce module
n'a pas de qualité (``None``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any, Literal

from pydantic import BaseModel

STORED_KEY = "qualite_entrees"
OPEN_METEO_WARNING = "prevision_open_meteo"
TARGET_DAYS = 6  # past.SAME_WEEKDAY_OCCURRENCES
MIN_DAYS = 3  # past.MIN_DAYS_PER_HOUR : en dessous, l'heure n'a pas de consommation habituelle
MIN_SPREAD_DAYS = 3  # jours complets pour juger de la régularité

# Écart type des consommations journalières, en % de la moyenne.
REGULAR_PERCENT = 15.0
IRREGULAR_PERCENT = 30.0
# Heures sans consommation habituelle (comptées à zéro) à partir desquelles le critère est faible.
MANY_MISSING_HOURS = 6
# Jours d'avance de la prévision météo : moyenne à partir de 2, faible à partir de 4.
FAIR_AHEAD = 2
POOR_AHEAD = 4

# Poids des critères dans la note d'ensemble.
WEIGHTS = {
    "consumption_history": 3.0,
    "consumption_regularity": 2.0,
    "solar_source": 2.0,
    "weather_horizon": 2.0,
    "cycle_profiles": 1.0,
    "history_import": 3.0,
}
GOOD_SCORE = 0.8
FAIR_SCORE = 0.5

Level = Literal["good", "fair", "poor"]
POINTS: dict[str, float] = {"good": 1.0, "fair": 0.5, "poor": 0.0}


@dataclass(frozen=True)
class BaselineQuality:
    """Données derrière la consommation habituelle d'un jour (``past.baseline_detail``)."""

    days_per_hour: tuple[int, ...]  # jours comparables moyennés, par heure (0 : heure absente)
    same_weekday: bool  # faux : moins de 6 mêmes jours de la semaine, tous les jours servent
    spread_percent: float | None  # écart type des journées complètes, en % de leur moyenne


def spread_percent(totals: Sequence[float]) -> float | None:
    """Écart type des consommations journalières en % de leur moyenne ; ``None`` sans assez de
    journées ou sans consommation."""
    if len(totals) < MIN_SPREAD_DAYS:
        return None
    mean = fmean(totals)
    if mean <= 0:
        return None
    return round(pstdev(totals) / mean * 100, 1)


def stored(
    baseline: BaselineQuality | None,
    forecast_warnings: Sequence[Mapping[str, Any]],
    profile_status: Mapping[str, str],
) -> dict[str, Any]:
    """Ce que le plan garde de ses données, au format du plan (clés en français)."""
    found: dict[str, Any] = {
        "prevision_repli": any(w.get("code") == OPEN_METEO_WARNING for w in forecast_warnings),
        "profils_insuffisants": sorted(
            name for name, status in profile_status.items() if status == "insuffisant"
        ),
        "profils_appris": sum(1 for status in profile_status.values() if status == "ok"),
    }
    if baseline is not None:
        found["jours_par_heure"] = list(baseline.days_per_hour)
        found["memes_jours_semaine"] = baseline.same_weekday
        found["ecart_journalier_pct"] = baseline.spread_percent
    return found


class QualityFactor(BaseModel):
    """Un critère : code, niveau, paramètres des textes de l'interface."""

    code: str
    level: Level
    params: dict[str, Any] = {}


class ForecastQuality(BaseModel):
    """Qualité des prévisions d'une vue : niveau, note (0 à 100) et critères."""

    level: Level
    score: int
    factors: list[QualityFactor]


def _history(stored_: Mapping[str, Any]) -> QualityFactor | None:
    days = stored_.get("jours_par_heure")
    if not isinstance(days, list) or len(days) != 24:
        return None
    present = [d for d in days if d >= MIN_DAYS]
    missing = 24 - len(present)
    same = bool(stored_.get("memes_jours_semaine"))
    typical = min(present) if present else 0
    level: Level
    if not present or missing >= MANY_MISSING_HOURS:
        level = "poor"
    elif missing > 0 or not same or typical < TARGET_DAYS:
        level = "fair"
    else:
        level = "good"
    return QualityFactor(
        code="consumption_history",
        level=level,
        params={
            "days": min(typical, TARGET_DAYS) if same else typical,
            "target": TARGET_DAYS,
            "same_weekday": same,
            "missing_hours": missing,
        },
    )


def _regularity(stored_: Mapping[str, Any]) -> QualityFactor | None:
    spread = stored_.get("ecart_journalier_pct")
    if spread is None:
        return None
    level: Level = (
        "good" if spread <= REGULAR_PERCENT else "fair" if spread <= IRREGULAR_PERCENT else "poor"
    )
    return QualityFactor(
        code="consumption_regularity", level=level, params={"percent": round(spread)}
    )


def assess(state: Mapping[str, Any], days_ahead: int, solar: bool) -> ForecastQuality | None:
    """Qualité des prévisions du plan ``state`` vu à ``days_ahead`` jours (hier : -1) ; ``solar``
    : la maison produit. ``None`` pour un plan sans données gardées (calculé avant)."""
    stored_ = state.get(STORED_KEY)
    if not isinstance(stored_, Mapping):
        return None
    factors: list[QualityFactor] = []
    for factor in (_history(stored_), _regularity(stored_)):
        if factor is not None:
            factors.append(factor)
    if solar:
        fallback = bool(stored_.get("prevision_repli"))
        factors.append(
            QualityFactor(
                code="solar_source",
                level="fair" if fallback else "good",
                params={"fallback": fallback},
            )
        )
        ahead = max(days_ahead, 0)
        level: Level = "poor" if ahead >= POOR_AHEAD else "fair" if ahead >= FAIR_AHEAD else "good"
        factors.append(QualityFactor(code="weather_horizon", level=level, params={"days": ahead}))
    missing_profiles = list(stored_.get("profils_insuffisants") or [])
    if missing_profiles:
        factors.append(
            QualityFactor(
                code="cycle_profiles",
                level="fair",
                params={"devices": ", ".join(missing_profiles), "count": len(missing_profiles)},
            )
        )
    elif stored_.get("profils_appris"):
        factors.append(QualityFactor(code="cycle_profiles", level="good"))
    if state.get("historique_en_reprise"):
        factors.append(QualityFactor(code="history_import", level="poor"))
    if not factors:
        return None
    total = sum(WEIGHTS[f.code] for f in factors)
    score = sum(WEIGHTS[f.code] * POINTS[f.level] for f in factors) / total
    overall: Level = "good" if score >= GOOD_SCORE else "fair" if score >= FAIR_SCORE else "poor"
    # Un historique en reprise rend le plan provisoire : jamais « bonne ».
    if overall == "good" and any(f.code == "history_import" for f in factors):
        overall = "fair"
    # Les critères les plus faibles d'abord : ils expliquent le niveau.
    factors.sort(key=lambda f: POINTS[f.level])
    return ForecastQuality(level=overall, score=round(score * 100), factors=factors)
