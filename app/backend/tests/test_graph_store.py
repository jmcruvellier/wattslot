"""Magasin du graphe : ``flush`` différés des petits lots (volume ou temps écoulé)."""

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from wattslot.storage.graph import FLUSH_INTERVAL, GraphStore

QUAD = '<urn:a> <urn:p> "{}" <urn:g> .\n'


def test_deferred_writes_flush_once_the_interval_has_passed(tmp_path: Path) -> None:
    """Des lots réguliers : le flush arrive quand même au bout de l'intervalle (le temps écoulé
    se compte depuis le dernier flush, pas depuis la dernière écriture)."""
    clock = [0.0]
    graph = GraphStore(tmp_path, clock=lambda: clock[0])
    step = FLUSH_INTERVAL.total_seconds() / 6

    for k in range(6):
        clock[0] = k * step
        graph.add_nquads(QUAD.format(k), deferred=True)
    assert graph._unflushed == 6  # pas encore vidé sur disque
    assert graph.quad_count() == 6  # mais lisible

    clock[0] = 6 * step
    graph.add_nquads(QUAD.format(6), deferred=True)
    assert graph._unflushed == 0
    assert graph._flushed_at == clock[0]


def test_graph_is_flushed_once_a_day() -> None:
    """Un flush par heure faisait réécrire à RocksDB, chaque heure, les données accumulées
    depuis le dernier compactage complet (2 Go écrits par jour sur une installation réelle)."""
    assert timedelta(hours=24) == FLUSH_INTERVAL


CRASH = """
import os, sys
from pathlib import Path
from wattslot.storage.graph import GraphStore
graph = GraphStore(Path(sys.argv[1]))
for k in range(200):
    graph.add_nquads('<urn:a> <urn:p> "%d" <urn:g> .\\n' % k, deferred=True)
assert graph._unflushed == 200
os._exit(0)  # coupure nette : ni flush, ni fermeture
"""


def test_deferred_writes_survive_a_killed_process(tmp_path: Path) -> None:
    """Entre deux flush, les écritures sont dans le journal de RocksDB : un processus coupé net
    (sans flush ni fermeture) n'en perd aucune."""
    subprocess.run([sys.executable, "-c", CRASH, str(tmp_path)], check=True, timeout=60)
    assert GraphStore(tmp_path).quad_count() == 200
