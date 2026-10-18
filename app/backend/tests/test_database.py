import sqlite3
from pathlib import Path

from wattslot.storage.database import (
    DATABASE_FILENAME,
    LEGACY_DATABASE_FILENAME,
    MIGRATIONS,
    migrate,
    open_database,
    schema_version,
)


def test_open_database_applies_all_migrations(tmp_path: Path) -> None:
    connection = open_database(tmp_path)

    assert schema_version(connection) == len(MIGRATIONS)
    connection.execute("INSERT INTO app_settings (key, value) VALUES ('langue', '\"fr\"')")


def test_migrations_are_applied_only_once(tmp_path: Path) -> None:
    open_database(tmp_path).close()
    connection = open_database(tmp_path)

    assert migrate(connection) == len(MIGRATIONS)
    rows = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
    assert rows[0] == len(MIGRATIONS)


def test_the_cycle_journal_is_emptied_once(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "base.db")
    connection.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
    )
    for version, statement in enumerate(MIGRATIONS[:10], start=1):
        connection.execute(statement)
        connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    connection.execute(
        "INSERT INTO appliance_days VALUES ('chauffe-eau', '2026-10-17', 'raw', '[]')"
    )

    migrate(connection)

    assert connection.execute("SELECT COUNT(*) FROM appliance_days").fetchone() == (0,)


def test_the_database_of_energy_optimizer_is_renamed(tmp_path: Path) -> None:
    legacy = sqlite3.connect(tmp_path / LEGACY_DATABASE_FILENAME)
    legacy.execute("PRAGMA journal_mode=WAL")
    migrate(legacy)
    with legacy:
        legacy.execute("INSERT INTO app_settings VALUES ('planning', '{}')")
    legacy.close()

    database = open_database(tmp_path)  # avant le renommage en WattSlot (lot 7.1)

    assert database.execute("SELECT key FROM app_settings").fetchall() == [("planning",)]
    assert (tmp_path / DATABASE_FILENAME).exists()
    assert not (tmp_path / LEGACY_DATABASE_FILENAME).exists()


def test_an_existing_wattslot_database_is_kept(tmp_path: Path) -> None:
    open_database(tmp_path).close()
    (tmp_path / LEGACY_DATABASE_FILENAME).write_bytes(b"ancienne")

    database = open_database(tmp_path)

    assert schema_version(database) == len(MIGRATIONS)
    assert (tmp_path / LEGACY_DATABASE_FILENAME).read_bytes() == b"ancienne"
