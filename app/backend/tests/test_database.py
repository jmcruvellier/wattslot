import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from wattslot.storage import database
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


class _CutAfterTheMigration(sqlite3.Connection):
    """Coupure juste après une migration, avant que sa version soit notée."""

    cut = False

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if self.cut and sql.startswith("INSERT INTO schema_migrations"):
            raise sqlite3.OperationalError("coupure de courant")
        return super().execute(sql, *args)


def test_a_migration_cut_before_its_version_is_replayed_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La migration et sa version vont ensemble : coupée entre les deux, elle est annulée et
    rejouée au démarrage suivant, au lieu d'échouer (« duplicate column ») à chaque démarrage."""
    connection = sqlite3.connect(tmp_path / "base.db", factory=_CutAfterTheMigration)
    migrate(connection)
    applied = schema_version(connection)
    monkeypatch.setattr(
        database,
        "MIGRATIONS",
        (*database.MIGRATIONS, "ALTER TABLE app_settings ADD COLUMN essai TEXT"),
    )

    connection.cut = True
    with pytest.raises(sqlite3.OperationalError, match="coupure"):
        migrate(connection)
    connection.cut = False

    assert migrate(connection) == applied + 1
    columns = [row[1] for row in connection.execute("PRAGMA table_info(app_settings)")]
    assert columns.count("essai") == 1


def _in_thread(action: Any) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(action).result()


def test_each_thread_has_its_own_transaction(tmp_path: Path) -> None:
    """Le ``commit`` d'un fil ne valide plus l'écriture en cours d'un autre (#151) : partagée,
    la connexion mélangeait les transactions des fils."""
    db = open_database(tmp_path)
    started = threading.Event()
    committed = threading.Event()

    def unfinished_write() -> None:
        db.execute("INSERT INTO app_settings (key, value) VALUES ('du_fil', '1')")
        started.set()
        committed.wait(5)
        db.rollback()  # abandonnée : ne doit pas avoir été validée par l'autre fil

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(unfinished_write)
        assert started.wait(5)
        with db:  # transaction du fil principal, validée pendant que l'autre est ouverte
            db.execute("INSERT INTO app_settings (key, value) VALUES ('du_principal', '1')")
        committed.set()
        writer.result()

    keys = {row[0] for row in db.execute("SELECT key FROM app_settings")}
    assert "du_principal" in keys and "du_fil" not in keys


def test_threads_read_and_write_at_the_same_time(tmp_path: Path) -> None:
    """Lectures et écritures concurrentes, comme les vues pendant l'ingestion : ni erreur ni
    ligne vide (« not enough values to unpack (expected 5, got 0) », #151)."""
    db = open_database(tmp_path)
    with db:
        db.executemany(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            [(f"cle_{i}", "x" * 50) for i in range(200)],
        )

    def read() -> int:
        widths = set()
        for _ in range(30):
            rows = db.execute("SELECT key, value, key, value, key FROM app_settings").fetchall()
            widths |= {len(row) for row in rows}
        assert widths == {5}
        return len(widths)

    def write(start: int) -> int:
        for i in range(start, start + 30):
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                    (f"ecrit_{i}", str(i)),
                )
        return 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read) for _ in range(6)]
        futures += [pool.submit(write, n * 100) for n in range(2)]
        for future in futures:
            future.result()  # relève une erreur d'un fil

    count = db.execute("SELECT COUNT(*) FROM app_settings WHERE key LIKE 'ecrit_%'").fetchone()
    assert count == (60,)


def test_close_closes_the_connections_of_every_thread(tmp_path: Path) -> None:
    db = open_database(tmp_path)
    mine = db.connection()  # type: ignore[attr-defined]
    other = _in_thread(db.connection)  # type: ignore[attr-defined]
    assert mine is not other

    db.close()

    for connection in (mine, other):
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
    assert db.execute("SELECT 1").fetchone() == (1,)  # rouverte au besoin


def test_connection_of_a_finished_thread_is_closed(tmp_path: Path) -> None:
    """La connexion d'un fil arrêté est fermée à l'ouverture de la suivante : gardées jusqu'à
    l'arrêt, elles s'accumulaient à chaque rafale de requêtes (fils de l'API arrêtés après 10 s
    sans requête)."""
    db = open_database(tmp_path)
    assert database.open_connections(db) == 1  # celle du fil principal (migrations)

    orphan = _in_thread(lambda: db.execute("SELECT 1").connection)  # fil arrêté au retour
    assert database.open_connections(db) == 2

    for _ in range(5):
        _in_thread(lambda: db.execute("SELECT COUNT(*) FROM app_settings").fetchone())
    assert database.open_connections(db) == 2  # le fil principal et le dernier fil
    with pytest.raises(sqlite3.ProgrammingError):
        orphan.execute("SELECT 1")  # fermée

    db.execute("SELECT 1")  # celle du fil principal sert toujours
    db.close()


def test_open_connections_is_unknown_for_a_plain_connection() -> None:
    assert database.open_connections(sqlite3.connect(":memory:")) is None
    assert database.open_connections(None) is None
