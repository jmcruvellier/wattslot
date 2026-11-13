"""Base SQLite de l'application et migrations de son schéma.

Chaque migration est appliquée une seule fois, dans l'ordre, et son numéro est noté dans
``schema_migrations``. Une migration publiée ne se modifie plus : on en ajoute une nouvelle.

La base est lue et écrite depuis la boucle et depuis de nombreux fils (``asyncio.to_thread`` :
ingestion, agrégation, vues, calcul, maintenance…). Chaque fil a sa propre connexion
(``ThreadConnections``), donc sa propre transaction : partagée, une connexion mélangeait les
transactions des fils et échouait sous Linux (« bad parameter or other API misuse », lignes
vides ; #37, #151). En mode WAL, les lecteurs ne bloquent pas l'écrivain et SQLite fait attendre
les écrivains entre eux (``BUSY_TIMEOUT_S``).
"""

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, cast

DATABASE_FILENAME = "wattslot.db"
# Attente d'une écriture d'un autre fil avant « database is locked » : l'import de l'historique
# écrit par lots de quelques secondes au plus.
BUSY_TIMEOUT_S = 30.0
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
    # 12 : corrections des agrégats (lot qualité des données) : une par période corrigée,
    # annulée (``undone_at``) plutôt que supprimée ; les agrégats eux-mêmes ne changent pas.
    """
    CREATE TABLE quality_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id TEXT NOT NULL,
        period TEXT NOT NULL,
        start TEXT NOT NULL,
        kind TEXT NOT NULL,
        method TEXT NOT NULL,
        original_kwh REAL,
        corrected_kwh REAL,
        automatic INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        undone_at TEXT
    )
    """,
    # 13 : index des corrections par capteur et période.
    "CREATE INDEX quality_corrections_period ON quality_corrections (entity_id, period, start)",
    # 14 et 15 : baisse d'un compteur en suspens (coupure ou remise à zéro, ``aggregation.Drop``),
    # reportée d'une période à la suivante comme le dernier relevé.
    "ALTER TABLE aggregation_state ADD COLUMN drop_time TEXT",
    "ALTER TABLE aggregation_state ADD COLUMN drop_value REAL",
    # 16 : valeurs négatives signalées à partir de -0,05 kWh (avant : -0,001) ; les corrections
    # automatiques de l'arrondi des statistiques de HA sont annulées (gardées, pour la trace).
    """
    UPDATE quality_corrections SET undone_at = created_at
    WHERE kind = 'negative' AND automatic = 1 AND undone_at IS NULL AND original_kwh >= -0.05
    """,
    # 17 : départs choisis par l'utilisateur parmi ceux que le plan propose, un par appareil et
    # par jour, imposés au calcul de ce jour.
    """
    CREATE TABLE chosen_starts (
        day TEXT NOT NULL,
        device TEXT NOT NULL,
        start_min INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (day, device)
    )
    """,
    # 18 : planification annulée par l'utilisateur pour le jour (« Annuler » de la frise et de
    # « Prochaine action ») : l'équipement n'est plus placé par les calculs de ce jour ; un choix
    # d'un autre jour ne sert plus.
    """
    CREATE TABLE cancelled_tasks (
        day TEXT NOT NULL,
        device TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (day, device)
    )
    """,
    # 19 : ressources de l'application minute par minute (courbes des dernières 24 h, gardées
    # après un redémarrage) : charge de la minute en % d'un cœur, mémoire, espace libre,
    # dernière taille mesurée du dossier des données.
    """
    CREATE TABLE resource_minutes (
        time TEXT PRIMARY KEY,
        cpu_percent REAL,
        memory_bytes INTEGER,
        disk_free_bytes INTEGER,
        disk_used_bytes INTEGER
    )
    """,
    # 20 : résumé des ressources heure par heure, gardé 30 jours (seuils des alertes, fuite de
    # mémoire sur plusieurs jours).
    """
    CREATE TABLE resource_hours (
        hour TEXT PRIMARY KEY,
        samples INTEGER NOT NULL,
        cpu_avg REAL,
        cpu_max REAL,
        memory_min INTEGER,
        memory_avg INTEGER,
        memory_max INTEGER,
        disk_free_min INTEGER,
        disk_used_max INTEGER
    )
    """,
    # 21 et 22 : octets écrits sur disque par minute et par heure (usure d'une carte SD ou d'un
    # SSD, effet des compactages du graphe).
    "ALTER TABLE resource_minutes ADD COLUMN written_bytes INTEGER",
    "ALTER TABLE resource_hours ADD COLUMN written_bytes INTEGER",
    # 23 : journal des calculs (``planning/run_log.py``) : ce que chaque calcul a annoncé pour
    # chaque équipement, gardé quelques jours et joint au rapport anonymisé.
    """
    CREATE TABLE plan_runs (
        at TEXT PRIMARY KEY,
        day TEXT NOT NULL,
        manual INTEGER NOT NULL,
        devices TEXT NOT NULL
    )
    """,
    # 24 : lancements déclarés par l'utilisateur (« C'est lancé » de « Prochaine action ») :
    # l'appareil n'est plus proposé ce jour-là, sur aucun navigateur ni après un nouveau calcul.
    """
    CREATE TABLE declared_launches (
        day TEXT NOT NULL,
        device TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (day, device)
    )
    """,
)


def schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def migrate(connection: sqlite3.Connection) -> int:
    """Applique les migrations manquantes ; renvoie la version du schéma obtenue."""
    if connection.in_transaction:  # écritures de l'appelant validées avant les migrations
        connection.commit()
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    current = schema_version(connection)
    for version, statement in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        # Une transaction pour la migration et sa version : le module sqlite3 n'en ouvre pas
        # avant un CREATE ou un ALTER. Sans elle, une coupure entre les deux laissait la
        # migration faite mais non notée, rejouée au démarrage suivant (« duplicate column ») :
        # l'application ne démarrait plus.
        with connection:
            connection.execute("BEGIN")
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


def _connect(path: Path) -> sqlite3.Connection:
    # check_same_thread=False : la connexion ne sert qu'à son fil, mais ``close`` les ferme
    # toutes depuis celui de l'arrêt.
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


class ThreadConnections:
    """Une connexion SQLite par fil, derrière l'interface d'une connexion : ``execute``,
    ``with database:`` (transaction du fil appelant), ``commit``, ``backup``… sont ceux de la
    connexion du fil qui appelle. Ouverte à la première utilisation dans un fil.

    Les fils qui servent les routes de l'API ne vivent pas toujours : au-delà d'un seul, ils
    s'arrêtent après 10 s sans requête. La connexion d'un fil arrêté est fermée à l'ouverture de
    la suivante ; gardée jusqu'à l'arrêt de l'application, chacune tenait sa mémoire et ses
    fichiers ouverts, et leur nombre montait à chaque page chargée."""

    def __init__(self, path: Path, connect: Callable[[Path], sqlite3.Connection] = _connect):
        self._path = path
        self._connect = connect
        self._local = threading.local()
        self._opened: list[tuple[threading.Thread, sqlite3.Connection]] = []
        self._lock = threading.Lock()

    def connection(self) -> sqlite3.Connection:
        """Connexion du fil appelant."""
        found: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if found is None:
            found = self._connect(self._path)
            self._local.connection = found
            with self._lock:
                orphans = [c for thread, c in self._opened if not thread.is_alive()]
                self._opened = [(t, c) for t, c in self._opened if t.is_alive()]
                self._opened.append((threading.current_thread(), found))
            for orphan in orphans:
                orphan.close()
        return found

    def open_count(self) -> int:
        """Connexions ouvertes, tous fils confondus."""
        with self._lock:
            return len(self._opened)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection(), name)

    def __enter__(self) -> "ThreadConnections":
        self.connection().__enter__()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> bool | None:
        return self.connection().__exit__(kind, error, trace)

    def close(self) -> None:
        """Ferme les connexions de tous les fils (arrêt de l'application)."""
        with self._lock:
            opened, self._opened = self._opened, []
            self._local = threading.local()
        for _, connection in opened:
            connection.close()


def open_connections(database: sqlite3.Connection | None) -> int | None:
    """Connexions ouvertes de la base de l'application ; ``None`` pour une connexion simple."""
    return database.open_count() if isinstance(database, ThreadConnections) else None


def open_database(data_dir: Path) -> sqlite3.Connection:
    """Base de l'application, migrée ; une connexion par fil (``ThreadConnections``), vue par
    le reste du code comme une ``sqlite3.Connection``."""
    _rename_legacy_database(data_dir)
    database = ThreadConnections(data_dir / DATABASE_FILENAME)
    migrate(database.connection())
    return cast(sqlite3.Connection, database)
