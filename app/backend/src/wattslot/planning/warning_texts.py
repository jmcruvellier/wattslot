"""Texte des avertissements du plan (lot 5.7), dans les six langues.

Repris du dashboard de la v1 (``texte_avertissement``), supprimé au lot 7.1 : mêmes codes, mêmes
paramètres bruts (nom interne d'équipement, minutes depuis minuit, date ISO…), mêmes textes en
français et en anglais. Catalogues dans ``planning/locales/warnings``.
"""

import json
from collections.abc import Mapping
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

from wattslot.languages import DEFAULT, language_of, number

LOCALES = Path(__file__).parent / "locales" / "warnings"


@cache
def catalog(lang: str) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
    return found


def _text(lang: str, section: str, key: str) -> str | None:
    value = catalog(lang).get(section, {}).get(key)
    return value if isinstance(value, str) else None


def _twelve(h: int) -> tuple[int, str]:
    """14 → (2, "PM") ; 0 et 24 → (12, "AM")."""
    h %= 24
    return (h % 12 or 12, "AM" if h < 12 else "PM")


def hour(h: int, lang: str) -> str:
    """Heure ronde : « 14h », « 2 PM », « 14:00 »."""
    if lang == "fr":
        return f"{h}h"
    if lang == "en":
        twelve, suffix = _twelve(h)
        return f"{twelve} {suffix}"
    return f"{h % 24}:00"


def hour_minutes(minutes: int, lang: str) -> str:
    """Heure à la minute depuis minuit, minutes omises à l'heure pile en français et en
    anglais : « 10h » / « 11h20 », « 10 AM » / « 11:20 AM », « 11:20 »."""
    h, m = divmod(int(minutes), 60)
    if lang not in ("fr", "en"):
        return f"{h % 24}:{m:02d}"
    if m == 0:
        return hour(h, lang)
    if lang == "en":
        twelve, suffix = _twelve(h)
        return f"{twelve}:{m:02d} {suffix}"
    return f"{h}h{m:02d}"


def duration(minutes: int, lang: str) -> str:
    """Durée : « 2h » / « 1h20 » en français, « 2 h » / « 1 h 20 min » ailleurs."""
    h, m = divmod(int(minutes), 60)
    if lang == "fr":
        return f"{h}h{m:02d}" if m else f"{h}h"
    return f"{h} h {m} min" if m else f"{h} h"


def long_date(day: Any, lang: str) -> str:
    """Date en toutes lettres (« Dimanche 18 Octobre 2026 »…), noms des jours et des mois dans
    les catalogues ; une valeur illisible est rendue telle quelle."""
    if isinstance(day, str):
        try:
            day = date.fromisoformat(day)
        except ValueError:
            return str(day)
    if not isinstance(day, date):
        return str(day)
    names: dict[str, str] = catalog(lang)["date"]
    return names["format"].format(
        jour=names[f"jour_{day.weekday()}"],
        num=day.day,
        mois=names[f"mois_{day.month}"],
        annee=day.year,
    )


def device_name(name: str, lang: str) -> str:
    """Nom affiché d'un équipement de la v1 ; un nom inconnu s'affiche tel quel."""
    return _text(lang, "equipement", name) or _text(DEFAULT, "equipement", name) or name


def _param(name: str, value: Any, lang: str) -> str:
    if name in ("equipement", "depend_de"):
        return device_name(str(value), lang)
    if name == "debut_min":
        return hour_minutes(int(value), lang)
    if name == "duree_min":
        return duration(int(value), lang)
    if name == "jour" or name.startswith("jour_"):
        return long_date(value, lang)
    if name.startswith("heure"):
        return hour(int(value), lang)
    if name.startswith("kwh") or name == "limite":
        return number(float(value), lang, 0 if abs(float(value)) >= 100 else 1)
    return str(value)


def warning_text(warning: Mapping[str, Any] | str, lang: str = DEFAULT) -> str:
    """Texte d'un avertissement dans la langue demandée ; une chaîne (cache antérieur aux
    avertissements structurés) s'affiche telle quelle, un code inconnu aussi."""
    if isinstance(warning, str):
        return warning
    language = language_of(lang)
    code = str(warning.get("code", ""))
    template = _text(language, "avertissement", code) or _text(DEFAULT, "avertissement", code)
    if template is None:
        return code
    params = {
        name: _param(name, value, language) for name, value in warning.get("params", {}).items()
    }
    return template.format(**params) if params else template
