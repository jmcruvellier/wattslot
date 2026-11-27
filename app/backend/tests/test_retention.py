"""Durées de conservation (``retention.py``) : valeurs par défaut, bornes, migration."""

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from wattslot.retention import (
    HOUR_DAYS,
    RETENTION_KEY,
    Retention,
    cutoff,
    load_retention,
    save_retention,
)
from wattslot.storage import database as database_module
from wattslot.storage.database import MIGRATIONS, migrate, open_database

PARIS = ZoneInfo("Europe/Paris")
HOURS_MIGRATION = 30  # heures gardées 15 mois là où elles l'étaient sans limite


def test_hours_are_kept_fifteen_months_by_default(tmp_path: Path) -> None:
    assert HOUR_DAYS == 456
    assert load_retention(open_database(tmp_path)) == Retention(
        raw_days=3, quarter_days=35, hour_days=456
    )


def test_hours_can_be_kept_three_months_ten_years_or_without_limit() -> None:
    assert Retention(hour_days=92).hour_days == 92
    assert Retention(hour_days=3660).hour_days == 3660
    assert Retention(hour_days=None).hour_days is None  # sans limite
    with pytest.raises(ValidationError):
        Retention(hour_days=91)  # le calcul lit 63 jours : trois mois au moins
    with pytest.raises(ValidationError):
        Retention(hour_days=3661)


def test_cutoff_is_midnight_at_home() -> None:
    today = date(2026, 11, 27)
    assert cutoff(456, today, PARIS) == datetime(2025, 8, 27, 22, tzinfo=UTC)  # minuit, heure d'été
    assert cutoff(92, today, PARIS) == datetime(2026, 8, 26, 22, tzinfo=UTC)
    assert cutoff(None, today, PARIS) is None


def _database_before_the_migration(tmp_path: Path, saved: str | None) -> sqlite3.Connection:
    """Base au schéma d'avant la migration des heures, avec la conservation enregistrée."""
    connection = sqlite3.connect(tmp_path / "avant.db")
    connection.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    for version, statement in enumerate(MIGRATIONS[: HOURS_MIGRATION - 1], start=1):
        connection.execute(statement)
        connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    if saved is not None:
        connection.execute("INSERT INTO app_settings VALUES (?, ?)", (RETENTION_KEY, saved))
    connection.commit()
    return connection


def test_update_bounds_the_hours_of_an_existing_installation(tmp_path: Path) -> None:
    """Jusque-là sans limite faute de réglage : 15 mois à la mise à jour, le reste gardé."""
    connection = _database_before_the_migration(
        tmp_path, json.dumps({"raw_days": 7, "quarter_days": 90, "hour_days": None})
    )

    assert migrate(connection) == len(MIGRATIONS)

    assert load_retention(connection) == Retention(raw_days=7, quarter_days=90, hour_days=456)


def test_update_keeps_a_chosen_duration_and_an_untouched_default(tmp_path: Path) -> None:
    chosen = _database_before_the_migration(
        tmp_path, json.dumps({"raw_days": 3, "quarter_days": 35, "hour_days": 400})
    )
    migrate(chosen)
    assert load_retention(chosen).hour_days == 400

    (tmp_path / "neuf").mkdir()
    untouched = _database_before_the_migration(tmp_path / "neuf", None)
    migrate(untouched)
    assert load_retention(untouched).hour_days == 456  # rien d'enregistré : la valeur par défaut


def test_without_limit_chosen_after_the_update_is_kept(tmp_path: Path) -> None:
    """La migration ne passe qu'une fois : « sans limite » choisi ensuite reste sans limite."""
    database = open_database(tmp_path)
    save_retention(database, Retention(hour_days=None))
    database.close()

    assert load_retention(open_database(tmp_path)).hour_days is None
    assert database_module.schema_version(open_database(tmp_path).connection()) == len(MIGRATIONS)  # type: ignore[attr-defined]
