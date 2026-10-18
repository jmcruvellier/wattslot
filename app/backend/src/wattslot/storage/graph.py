"""Magasin Oxigraph embarqué.

Intégré comme bibliothèque (``pyoxigraph``) dans le processus de l'application : choix du lot 0.2
confirmé par le banc du lot 0.5 (``bench/``). Le reste du code ne passe que
par ``GraphStore``.

Règles : écritures par lots suivis d'un ``flush``, jamais de transaction
de plusieurs millions de triplets ; graphes nommés explicitement dans les requêtes. Les petites
écritures régulières (agrégats en temps réel) diffèrent leur ``flush`` comme le brut
(``storage/raw.py``) : chaque ``flush`` crée de petits fichiers que RocksDB recompacte.

Les remplacements de graphe (vider, puis remplir : deux transactions) et la copie de sauvegarde
(``backup``) prennent le même verrou : une copie ne voit jamais un graphe à moitié remplacé.
"""

import io
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import pyoxigraph

from wattslot.storage.raw import FLUSH_INTERVAL, FLUSH_TRIPLES

GRAPH_DIRNAME = "oxigraph"


class GraphStore:
    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.monotonic) -> None:
        path = data_dir / GRAPH_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        self._store = pyoxigraph.Store(str(path))
        self._clock = clock
        self._unflushed = 0  # quadruplets écrits par add_nquads(deferred=True) depuis le flush
        self._flushed_at = clock()
        self._replacing = threading.Lock()

    def quad_count(self) -> int:
        return len(self._store)

    def replace_graph_turtle(self, graph: str, turtle: bytes, base_iri: str) -> None:
        """Remplace un petit graphe (vocabulaire) par le contenu d'un fichier Turtle."""
        node = pyoxigraph.NamedNode(graph)
        with self._replacing:
            self._store.clear_graph(node)
            self._store.load(
                turtle, format=pyoxigraph.RdfFormat.TURTLE, base_iri=base_iri, to_graph=node
            )
            self._store.flush()

    def turtle(self, graph: str) -> bytes:
        """Contenu d'un graphe en Turtle (export de la maison, lot 3.8)."""
        found = self._store.dump(
            format=pyoxigraph.RdfFormat.TURTLE, from_graph=pyoxigraph.NamedNode(graph)
        )
        assert found is not None
        return found

    def quads(self, graph: str) -> list[pyoxigraph.Quad]:
        """Quadruplets d'un petit graphe (migration de l'espace de noms, lot 7.1)."""
        return list(self._store.quads_for_pattern(None, None, None, pyoxigraph.NamedNode(graph)))

    def replace_graph(self, graph: str, triples: Iterable[pyoxigraph.Triple]) -> None:
        """Remplace un petit graphe (modèle de la maison) par ces triplets."""
        node = pyoxigraph.NamedNode(graph)
        with self._replacing:
            self._store.clear_graph(node)
            self._store.extend(
                pyoxigraph.Quad(t.subject, t.predicate, t.object, node) for t in triples
            )
            self._store.flush()

    def add_nquads(self, nquads: str, deferred: bool = False) -> None:
        """Ajoute un lot de quadruplets (N-Quads, graphes nommés), suivi d'un ``flush`` ;
        ``deferred`` : petit lot régulier, ``flush`` selon le volume et le temps écoulé."""
        self._store.load(nquads.encode(), format=pyoxigraph.RdfFormat.N_QUADS)
        if not deferred:
            self.flush()
            return
        self._unflushed += nquads.count("\n")
        elapsed = self._clock() - self._flushed_at
        if self._unflushed >= FLUSH_TRIPLES or elapsed >= FLUSH_INTERVAL.total_seconds():
            self.flush()

    def bulk_add_nquads(self, lines: list[str]) -> None:
        """Ajoute un gros lot de quadruplets (reprise de l'historique) par le chargeur en masse :
        fichiers triés écrits directement dans RocksDB, sans journal ni ``flush``, une seule
        recompaction pour tout le lot. ``lines`` (N-Quads) est vidée au fil de la lecture : le
        texte n'est jamais copié en entier. Pas atomique : un arrêt en cours de chargement en
        laisse une partie, que l'appelant doit pouvoir réécrire sans doublon."""
        reader = io.BufferedReader(_Consumed(lines), 1 << 20)
        self._store.bulk_load(reader, format=pyoxigraph.RdfFormat.N_QUADS)

    def select(self, sparql: str) -> Iterator[dict[str, str]]:
        """Résultats d'une requête SELECT, valeurs en texte (IRI ou littéral)."""
        solutions = self._store.query(sparql)
        assert isinstance(solutions, pyoxigraph.QuerySolutions)
        names = [v.value for v in solutions.variables]
        for solution in solutions:
            yield {name: solution[name].value for name in names if solution[name] is not None}

    def update(self, sparql: str) -> None:
        """Mise à jour SPARQL (une transaction : à garder petite), suivie d'un ``flush``."""
        self._store.update(sparql)
        self._store.flush()

    def named_graphs(self, prefix: str = "") -> list[str]:
        return sorted(g.value for g in self._store.named_graphs() if g.value.startswith(prefix))

    def remove_graph(self, graph: str) -> None:
        """Retire un graphe nommé, à vider d'abord par petits lots (règles de mémoire)."""
        self._store.remove_graph(pyoxigraph.NamedNode(graph))
        self._store.flush()

    def optimize(self) -> None:
        """Compactage (RocksDB) : rend la place laissée par les suppressions."""
        self._store.optimize()

    def backup(self, target: Path) -> None:
        """Copie cohérente du magasin dans ``target`` (qui ne doit pas exister) : point de
        contrôle de RocksDB, en liens physiques sur le même disque (sauvegarde à chaud)."""
        with self._replacing:
            self.flush()
            self._store.backup(str(target))

    def flush(self) -> None:
        self._store.flush()
        self._unflushed = 0
        self._flushed_at = self._clock()


class _Consumed(io.RawIOBase):
    """Lecture d'une liste de textes, vidée au fur et à mesure."""

    def __init__(self, lines: list[str]) -> None:
        lines.reverse()  # retirés par la fin, sans recopier la liste
        self._lines = lines
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: "memoryview | bytearray") -> int:  # type: ignore[override]
        while len(self._pending) < len(buffer) and self._lines:
            self._pending += self._lines.pop().encode()
        size = min(len(buffer), len(self._pending))
        buffer[:size] = self._pending[:size]
        self._pending = self._pending[size:]
        return size
