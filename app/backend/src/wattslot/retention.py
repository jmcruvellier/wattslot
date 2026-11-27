"""Durées de conservation des données, réglables et gardées en base (``app_settings``).

- **Brut** : 3 jours.
- **Quarts d'heure** : 35 jours (profils de cycle sur 30 jours).
- **Heures** : 15 mois (``HOUR_DAYS``), ou sans limite (``None``). Le calcul ne relit que 9
  semaines d'heures (``planning/past.py``) ; au-delà, les heures ne servent qu'à l'assistant
  (énergie d'un jour passé) et à d'éventuelles prévisions fondées sur l'année précédente, qui
  demandent un peu plus de 13 mois. Gardées sans limite, elles faisaient l'essentiel du disque :
  3,8 Go sur une installation réelle reprise depuis 2023 (82 capteurs, environ 1,6 Ko par
  agrégat), dont l'application ne lisait jamais plus de 6 %.

La maintenance de la nuit retire ce qui a passé sa durée (``maintenance.py``) ; la reprise de
l'historique de Home Assistant ne remonte pas au-delà (``aggregation.py``).
"""

import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

RETENTION_KEY = "retention"
HOUR_DAYS = 456  # 15 mois
# Le calcul lit 63 jours d'heures : trois mois laissent une marge.
HOUR_DAYS_MIN = 92


class Retention(BaseModel):
    """Durées de conservation, en jours."""

    raw_days: int = Field(default=3, ge=1, le=30)
    quarter_days: int = Field(
        default=35, ge=31, le=3660
    )  # au moins les 30 jours des profils de cycle
    hour_days: int | None = Field(default=HOUR_DAYS, ge=HOUR_DAYS_MIN, le=3660)  # None : tout


def load_retention(database: sqlite3.Connection) -> Retention:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (RETENTION_KEY,)
    ).fetchone()
    return Retention.model_validate(json.loads(row[0])) if row else Retention()


def save_retention(database: sqlite3.Connection, retention: Retention) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (RETENTION_KEY, retention.model_dump_json()),
        )


def cutoff(days: int | None, today: date, zone: ZoneInfo) -> datetime | None:
    """Début (UTC) de ce qui est gardé : minuit, heure de la maison, ``days`` jours avant
    ``today`` ; ``None`` sans limite."""
    if days is None:
        return None
    return datetime.combine(today - timedelta(days=days), time(), zone).astimezone(UTC)
