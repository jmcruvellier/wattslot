"""Devise de la maison (lot 7.3) : celle des prix saisis, des coûts et des textes.

Réglage de l'application (``/api/settings/currency``), enregistré dans ``app_settings`` ; sans
réglage, la devise de Home Assistant (``get_config``, Paramètres, Système, Général), sinon
l'euro. Changer de devise ne convertit aucun prix : les montants restent ceux saisis.

Les noms internes en ``_eur`` (tarif, indicateurs) désignent la devise de la maison. Les textes
du serveur (explications, recommandation, notifications) écrivent les montants avec
``amount`` ; l'interface les met en forme elle-même (``Intl.NumberFormat``).
"""

import json
import sqlite3
from dataclasses import dataclass

from pydantic import BaseModel, Field

from wattslot.languages import number

SETTINGS_KEY = "currency"
DEFAULT = "EUR"


@dataclass(frozen=True)
class Currency:
    symbol: str
    before_in_english: bool = False  # « $1.73 » en anglais, « 1,73 $ » ailleurs
    decimals: int = 2
    # Ordre de grandeur d'un euro dans la devise : les pénalités et départages du moteur, réglés
    # en euros, comparent des prix ramenés à cette échelle (``scale``). Approché à dessein : il
    # ne sert qu'à garder les mêmes priorités, jamais à convertir un montant.
    per_euro: float = 1.0


# Devises proposées dans les réglages ; une autre (code ISO 4217) s'affiche par son code.
CURRENCIES: dict[str, Currency] = {
    "EUR": Currency("€"),
    "CHF": Currency("CHF"),
    "GBP": Currency("£", before_in_english=True),
    "USD": Currency("$", before_in_english=True),
    "CAD": Currency("CA$", before_in_english=True, per_euro=1.5),
    "AUD": Currency("A$", before_in_english=True, per_euro=1.7),
    "NZD": Currency("NZ$", before_in_english=True, per_euro=1.8),
    "SEK": Currency("kr", per_euro=11),
    "NOK": Currency("kr", per_euro=11),
    "DKK": Currency("kr.", per_euro=7.5),
    "PLN": Currency("zł", per_euro=4.3),
    "CZK": Currency("Kč", per_euro=25),
    "HUF": Currency("Ft", decimals=0, per_euro=400),
    "RON": Currency("lei", per_euro=5),
    "BGN": Currency("лв", per_euro=2),
    "JPY": Currency("¥", before_in_english=True, decimals=0, per_euro=160),
}


class CurrencySetting(BaseModel):
    """Réglage enregistré : un code ISO 4217, ou ``None`` pour suivre Home Assistant."""

    code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class CurrencyState(BaseModel):
    """Réponse de l'API : réglage, devise de HA, devise retenue et devises proposées."""

    code: str | None
    home_assistant: str | None
    effective: str
    choices: list[str]


_saved: str | None = None
_home_assistant: str | None = None


def load(database: sqlite3.Connection) -> CurrencySetting:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (SETTINGS_KEY,)
    ).fetchone()
    return CurrencySetting.model_validate(json.loads(row[0])) if row else CurrencySetting()


def save(database: sqlite3.Connection, setting: CurrencySetting) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, setting.model_dump_json()),
        )
    use_saved(setting.code)


def use_saved(code: str | None) -> None:
    """Réglage en vigueur pour les textes du serveur (démarrage, enregistrement)."""
    global _saved
    _saved = code


def note_home_assistant(code: object) -> None:
    """Devise de la configuration de HA, relue avec chaque instantané."""
    global _home_assistant
    _home_assistant = code if isinstance(code, str) and len(code) == 3 else None


def active() -> str:
    return _saved or _home_assistant or DEFAULT


def state() -> CurrencyState:
    return CurrencyState(
        code=_saved, home_assistant=_home_assistant, effective=active(), choices=list(CURRENCIES)
    )


def scale(code: str | None = None) -> float:
    """Ordre de grandeur d'un euro dans la devise ; 1 pour une devise inconnue."""
    found = CURRENCIES.get(code or active())
    return found.per_euro if found else 1.0


def symbol(code: str | None = None) -> str:
    code = code or active()
    found = CURRENCIES.get(code)
    return found.symbol if found else code


def amount(
    value: float,
    lang: str,
    code: str | None = None,
    decimals: int | None = None,
    signed: bool = False,
) -> str:
    """Montant dans la langue : « 1,73 € », « $1.73 », « 1,73 CHF », « +0,20 € »."""
    code = code or active()
    found = CURRENCIES.get(code, Currency(code))
    digits = found.decimals if decimals is None else decimals
    text = number(value, lang, digits, signed=signed)
    if lang == "en" and found.before_in_english:
        sign = text[0] if text[0] in "+-" else ""
        return f"{sign}{found.symbol}{text[len(sign) :]}"
    return f"{text}\u00a0{found.symbol}"


def per_kwh(value: float, lang: str, code: str | None = None, decimals: int = 3) -> str:
    """Prix du kWh : « 0,138 €/kWh », « $0.138/kWh »."""
    return f"{amount(value, lang, code, decimals)}/kWh"
