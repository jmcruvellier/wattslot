"""Options de l'extension, réglées dans Home Assistant (lot 6t.3).

Le Supervisor les valide selon le ``schema`` de ``ha-addon/wattslot/config.yaml`` et les
écrit dans ``/data/options.json`` avant chaque démarrage (traductions dans ``translations/``).
En mode extension, elles l'emportent à chaque démarrage : niveau des journaux de l'application,
et conservation du brut et des quarts d'heure (écrite en base, ``maintenance.Retention`` ; celle
des heures reste réglable par l'API).
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from wattslot.maintenance import Retention, load_retention, save_retention

logger = logging.getLogger(__name__)

OPTIONS_FILENAME = "options.json"


class AddonOptions(BaseModel):
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    raw_days: int = Field(default=Retention().raw_days, ge=1, le=30)
    quarter_days: int = Field(default=Retention().quarter_days, ge=31, le=3660)


def load(data_dir: Path) -> AddonOptions:
    """Options lues dans ``options.json`` ; valeurs par défaut si le fichier manque ou est
    invalide (le Supervisor l'a pourtant validé : on ne bloque pas le démarrage)."""
    path = data_dir / OPTIONS_FILENAME
    try:
        return AddonOptions.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return AddonOptions()
    except (ValueError, ValidationError) as exc:
        logger.warning("Options de l'extension ignorées (%s) : valeurs par défaut", exc)
        return AddonOptions()


def apply_retention(database: sqlite3.Connection, options: AddonOptions) -> Retention:
    """Conservation du brut et des quarts d'heure prise dans les options."""
    retention = load_retention(database).model_copy(
        update={"raw_days": options.raw_days, "quarter_days": options.quarter_days}
    )
    save_retention(database, retention)
    return retention
