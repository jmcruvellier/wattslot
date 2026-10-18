"""Base SQLite de l'application et migrations de son schéma.

Chaque migration est appliquée une seule fois, dans l'ordre, et son numéro est noté dans
``schema_migrations``. Une migration publiée ne se modifie plus : on en ajoute une nouvelle.
"""

import sqlite3
from pathlib import Path

DATABASE_FILENAME = "wattslot.db"
# Nom d'avant le renommage en WattSlot (lot 7.1) : la base est renommée à l'ouverture.
LEGACY_DATABASE_FILENAME = "energy_optimizer.db"

MIGRATIONS: tuple[str, ...] = (
    # 1 : réglages de l'application (clé → valeur JSON).
    """
    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    # 2 : dernier relevé écrit par entité (reprise après coupure, lot 1.2).
    """
    CREATE TABLE ingestion_state (
        entity_id TEXT PRIMARY KEY,
        last_time TEXT NOT NULL,
        last_value REAL NOT NULL
    )
    """,
    # 3 : agrégation (lot 1.3) : par entité et par période, début de la prochaine période à
    # calculer et dernier relevé connu avant elle (valeur reportée en début de période).
    """
    CREATE TABLE aggregation_state (
        entity_id TEXT NOT NULL,
        period TEXT NOT NULL,
        next_start TEXT NOT NULL,
        carry_time TEXT,
        carry_value REAL,
        PRIMARY KEY (entity_id, period)
    )
    """,
    # 4 : reprise de l'historique de HA par entité (lot 1.3) : agrégats repris, le plus ancien.
    """
    CREATE TABLE history_import (
        entity_id TEXT PRIMARY KEY,
        imported_at TEXT NOT NULL,
        quarters INTEGER NOT NULL,
        quarter_since TEXT,
        hours INTEGER NOT NULL,
        hour_since TEXT
    )
    """,
    # 5 : journal des cycles des équipements (lot 2.2) : une ligne par équipement et par
    # journée complète, cycles en JSON ; source « raw » (brut) ou « quarters » (agrégats).
    """
    CREATE TABLE appliance_days (
        device_key TEXT NOT NULL,
        day TEXT NOT NULL,
        source TEXT NOT NULL,
        cycles TEXT NOT NULL,
        PRIMARY KEY (device_key, day)
    )
    """,
    # 6 : plans calculés (lot 2.3, remplacent les fichiers *.pkl de la v1) : aujourd'hui,
    # hier (archivé à la bascule), demain, horizon ; contenu JSON au format de la v1.
    """
    CREATE TABLE plans (
        kind TEXT PRIMARY KEY,
        day TEXT NOT NULL,
        content TEXT NOT NULL,
        computed_at TEXT NOT NULL,
        manual INTEGER NOT NULL,
        seconds REAL NOT NULL
    )
    """,
    # 7 : affectation des tâches en attente à un jour, d'un calcul à l'autre (lot 2.3).
    """
    CREATE TABLE task_assignments (
        uid TEXT PRIMARY KEY,
        day TEXT,
        reference TEXT NOT NULL,
        task TEXT NOT NULL,
        coverage REAL,
        coverage_today REAL
    )
    """,
    # 8 : demandes déclarées dans l'application (lot 4.5 de la phase 4) : un équipement à faire
    # tourner, au plus tard un jour donné ou sans date ; ouverte, faite ou annulée ; jour où un
    # calcul a constaté le lancement de l'équipement (close le lendemain).
    """
    CREATE TABLE requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device TEXT NOT NULL,
        created_at TEXT NOT NULL,
        latest TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        launched_on TEXT,
        closed_at TEXT
    )
    """,
    # 9 : notifications envoyées (lot 5.6) : une par notification, clé (équipement, cause…) et
    # jour, avec l'empreinte du texte (rythme « quand le plan change »).
    """
    CREATE TABLE notifications_sent (
        kind TEXT NOT NULL,
        key TEXT NOT NULL,
        day TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        PRIMARY KEY (kind, key, day)
    )
    """,
    # 10 : rappels demandés depuis l'écran Aujourd'hui (lot 6b.3) : un par appareil et par jour,
    # envoyé à l'heure de début que le plan du moment lui donne.
    """
    CREATE TABLE reminders (
        device TEXT NOT NULL,
        day TEXT NOT NULL,
        created_at TEXT NOT NULL,
        sent_at TEXT,
        PRIMARY KEY (device, day)
    )
    """,
    # 11 : journal des cycles vidé une fois (renommage en WattSlot, phase 7) : ses journées
    # calculées pendant la reprise de l'historique, ou avant la réécriture des relevés bruts,
    # étaient vides et gardées 30 jours (profil « insuffisant ») ; recalculées à la demande.
    "DELETE FROM appliance_days",
)


def schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def migrate(connection: sqlite3.Connection) -> int:
    """Applique les migrations manquantes ; renvoie la version du schéma obtenue."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    current = schema_version(connection)
    for version, statement in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        with connection:
            connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    return schema_version(connection)


def _rename_legacy_database(data_dir: Path) -> None:
    """Renomme ``energy_optimizer.db`` et ses fichiers du journal WAL, sauf si la base au nouveau
    nom existe déjà."""
    if (data_dir / DATABASE_FILENAME).exists() or not (
        data_dir / LEGACY_DATABASE_FILENAME
    ).exists():
        return
    for suffix in ("", "-wal", "-shm"):
        legacy = data_dir / f"{LEGACY_DATABASE_FILENAME}{suffix}"
        if legacy.exists():
            legacy.rename(data_dir / f"{DATABASE_FILENAME}{suffix}")


def open_database(data_dir: Path) -> sqlite3.Connection:
    _rename_legacy_database(data_dir)
    connection = sqlite3.connect(data_dir / DATABASE_FILENAME, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    migrate(connection)
    return connection
