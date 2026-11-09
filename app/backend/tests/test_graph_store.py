"""Magasin du graphe : ``flush`` différés des petits lots (volume ou temps écoulé)."""

from pathlib import Path

from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import FLUSH_INTERVAL

QUAD = '<urn:a> <urn:p> "{}" <urn:g> .\n'


def test_deferred_writes_flush_once_the_interval_has_passed(tmp_path: Path) -> None:
    """Des lots toutes les 10 minutes : le flush horaire arrive quand même (le temps écoulé se
    compte depuis le dernier flush, pas depuis la dernière écriture)."""
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
