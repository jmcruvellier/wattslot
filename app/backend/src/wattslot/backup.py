"""Sauvegarde à chaud de l'extension (lot 6t.3).

Home Assistant copie le dossier ``/data`` pendant que l'application tourne. Copier la base
RocksDB du graphe ou la base SQLite pendant qu'elles écrivent (ou que RocksDB compacte) donnerait
une sauvegarde incohérente. Les commandes de l'extension figent donc une copie :

- ``backup_pre`` (``python -m wattslot.backup prepare``) demande à l'application de
  créer ``/data/backup/`` : copie de SQLite par son API de sauvegarde, puis point de contrôle du
  graphe (``Store.backup`` : liens physiques, quasi instantané). SQLite d'abord : le graphe est
  au moins aussi avancé que l'état de l'agrégation, et un agrégat recalculé réécrit les mêmes
  triplets (IRI déterministes) ;
- ``backup_exclude`` (``config.yaml``) retire de la sauvegarde les fichiers vivants : HA ne copie
  que ``backup/``, qui ne bouge plus ;
- ``backup_post`` (``… finish``) supprime la copie, qui retiendrait sinon sur disque les fichiers
  que RocksDB compacte ensuite.

Rien n'est suspendu : l'ingestion et l'agrégation continuent pendant la copie de HA.

Après une restauration, le dossier de l'extension ne contient que ``backup/`` (et les réglages) :
``restore_snapshot`` remet la copie en place au démarrage. Les noms dans ``backup/`` diffèrent de
ceux des fichiers vivants : le Supervisor compare ``backup_exclude`` à la fin du chemin
(``PurePath.match``), et ``oxigraph`` exclurait aussi ``backup/oxigraph``.
"""

import logging
import shutil
import sqlite3
import sys
import urllib.request
from pathlib import Path

from wattslot.storage.database import DATABASE_FILENAME
from wattslot.storage.graph import GRAPH_DIRNAME, GraphStore

logger = logging.getLogger(__name__)

SNAPSHOT_DIRNAME = "backup"
PARTIAL_DIRNAME = "backup.partial"  # copie en cours : jamais restaurée
SNAPSHOT_GRAPH = "graph"
SNAPSHOT_DATABASE = "database.db"
LOCAL_URL = "http://127.0.0.1:8100/api/backup"
LOCAL_ADDRESSES = frozenset({"127.0.0.1", "::1"})


def prepare(data_dir: Path, database: sqlite3.Connection, graph: GraphStore) -> Path:
    """Crée ``backup/`` (remplace une copie restée d'une sauvegarde interrompue)."""
    partial = data_dir / PARTIAL_DIRNAME
    target = data_dir / SNAPSHOT_DIRNAME
    for path in (partial, target):
        shutil.rmtree(path, ignore_errors=True)
    partial.mkdir()
    copy = sqlite3.connect(partial / SNAPSHOT_DATABASE)
    try:
        database.backup(copy)
    finally:
        copy.close()
    graph.backup(partial / SNAPSHOT_GRAPH)
    partial.rename(target)
    return target


def finish(data_dir: Path) -> None:
    """Supprime la copie (après la sauvegarde de HA)."""
    for name in (PARTIAL_DIRNAME, SNAPSHOT_DIRNAME):
        shutil.rmtree(data_dir / name, ignore_errors=True)


def restore_snapshot(data_dir: Path) -> bool:
    """Au démarrage : remet en place la copie si la base et le graphe manquent (restauration
    d'une sauvegarde de HA) ; sinon, supprime une copie restée d'une sauvegarde interrompue.
    Renvoie vrai si la copie a été restaurée."""
    snapshot = data_dir / SNAPSHOT_DIRNAME
    shutil.rmtree(data_dir / PARTIAL_DIRNAME, ignore_errors=True)
    if not snapshot.is_dir():
        return False
    database = data_dir / DATABASE_FILENAME
    graph = data_dir / GRAPH_DIRNAME
    restored = not database.exists() and not graph.exists()
    if restored:
        (snapshot / SNAPSHOT_DATABASE).rename(database)
        (snapshot / SNAPSHOT_GRAPH).rename(graph)
        logger.info("Sauvegarde restaurée : base et graphe remis en place")
    shutil.rmtree(snapshot, ignore_errors=True)
    return restored


def _call(step: str) -> None:
    request = urllib.request.Request(f"{LOCAL_URL}/{step}", method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        response.read()


def main(argv: list[str]) -> int:
    """``python -m wattslot.backup prepare|finish`` (commandes de l'extension)."""
    if len(argv) != 1 or argv[0] not in ("prepare", "finish"):
        print("usage : python -m wattslot.backup prepare|finish", file=sys.stderr)
        return 2
    try:
        _call(argv[0])
    except OSError as exc:  # application injoignable ou erreur HTTP : sauvegarde en échec
        print(f"Sauvegarde : {argv[0]} impossible : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
