"""Migration de l'espace de noms d'avant le renommage en WattSlot (lot 7.1 de la phase 7).

Au démarrage, si le magasin a encore des graphes de l'ancien espace (``LEGACY_BASE``) :

- maison et configuration (quelques centaines de triplets) : réécrites sous le nouvel espace ;
- bibliothèque et schéma : retirés, ils sont rechargés depuis les fichiers à chaque démarrage ;
- relevés bruts (un magasin par jour, gardés 3 jours) : le capteur de chaque relevé est réécrit
  (``migrate_raw``) ; sinon les relevés d'avant la migration ne correspondent plus à la maison et
  les données réelles du jour restent vides jusqu'au redémarrage (constaté le 18/10/2026) ;
- agrégats : abandonnés. La reprise de l'historique de HA les recalcule sous le nouvel espace
  (table ``history_import`` vidée, curseurs de l'agrégation gardés). Les anciens graphes, qui
  peuvent compter des millions de triplets, sont vidés en arrière-plan après le démarrage
  (``drop_legacy_aggregates``), par petits lots : l'application répond pendant ce temps.
"""

import logging
import sqlite3
import threading
import time

import pyoxigraph

from wattslot.ontology import BASE, HOME, LEGACY_BASE, LEGACY_HOME
from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import SOSA, RawStores

logger = logging.getLogger(__name__)

LEGACY_GRAPHS = f"{LEGACY_BASE}/graph/"
LEGACY_AGGREGATES = f"{LEGACY_BASE}/graph/aggregates/"
# Graphes gardés et réécrits ; les autres (bibliothèque, schéma) sont rechargés.
KEPT = ("home", "configuration")
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DROP_BATCH = 2000  # agrégats retirés par transaction (règles de mémoire du magasin)


def renamed(iri: str) -> str:
    """IRI sous le nouvel espace de noms ; inchangée si elle n'est pas de l'ancien."""
    for old, new in ((LEGACY_BASE, BASE), (LEGACY_HOME, HOME)):
        if iri.startswith(old):
            return new + iri[len(old) :]
    return iri


def _term(term: object) -> object:
    return (
        pyoxigraph.NamedNode(renamed(term.value))
        if isinstance(term, pyoxigraph.NamedNode)
        else term
    )


def migrate(graph: GraphStore, database: sqlite3.Connection) -> bool:
    """Réécrit maison et configuration, retire bibliothèque et schéma, relance la reprise de
    l'historique ; vrai s'il y avait quelque chose à migrer. Les agrégats restent à vider : un
    redémarrage avant la fin ne relance pas la reprise (seuls restent alors des agrégats)."""
    legacy = [
        name for name in graph.named_graphs(LEGACY_GRAPHS) if not name.startswith(LEGACY_AGGREGATES)
    ]
    if not legacy:
        return False
    for name in legacy:
        if name.removeprefix(LEGACY_GRAPHS) in KEPT:
            triples = [
                pyoxigraph.Triple(_term(q.subject), _term(q.predicate), _term(q.object))  # type: ignore[arg-type]
                for q in graph.quads(name)
            ]
            graph.replace_graph(renamed(name), triples)
            logger.info("Espace de noms : %s triplets de %s réécrits", len(triples), name)
        graph.remove_graph(name)
    with database:
        database.execute("DELETE FROM history_import")
    logger.info("Espace de noms : agrégats recalculés depuis l'historique de Home Assistant")
    return True


def migrate_raw(raw: RawStores) -> int:
    """Réécrit sous le nouvel espace le capteur des relevés bruts (``sosa:madeBySensor``), capteur
    par capteur, dans chaque journée gardée ; renvoie le nombre de capteurs réécrits. Sans effet
    sur des relevés déjà migrés : à chaque démarrage, une requête par journée suffit à le voir."""
    renamed_sensors = 0
    for day in raw.days():
        store = raw.store(day)
        solutions = store.query(
            f"SELECT DISTINCT ?s WHERE {{ ?o <{SOSA}madeBySensor> ?s . "
            f'FILTER(STRSTARTS(STR(?s), "{LEGACY_HOME}")) }}'
        )
        assert isinstance(solutions, pyoxigraph.QuerySolutions)
        legacy = [solution["s"].value for solution in solutions]
        for sensor in legacy:
            store.update(
                f"DELETE {{ ?o <{SOSA}madeBySensor> <{sensor}> }} "
                f"INSERT {{ ?o <{SOSA}madeBySensor> <{renamed(sensor)}> }} "
                f"WHERE {{ ?o <{SOSA}madeBySensor> <{sensor}> }}"
            )
        if legacy:
            store.flush()
            renamed_sensors += len(legacy)
            logger.info(
                "Espace de noms : relevés bruts du %s réécrits (%s capteurs)",
                day,
                len(legacy),
            )
    return renamed_sensors


def drop_legacy_aggregates(graph: GraphStore, stop: threading.Event | None = None) -> int:
    """Vide puis retire les graphes d'agrégats de l'ancien espace, par lots de ``DROP_BATCH`` ;
    s'interrompt si ``stop`` est levé (arrêt de l'application : reprise au démarrage suivant).
    Renvoie le nombre d'agrégats retirés."""
    removed = 0
    began = time.monotonic()
    for name in graph.named_graphs(LEGACY_AGGREGATES):
        while True:
            if stop is not None and stop.is_set():
                return removed
            batch = [
                row["a"]
                for row in graph.select(
                    f"SELECT ?a WHERE {{ GRAPH <{name}> {{ ?a <{RDF_TYPE}> ?t }} }} "
                    f"LIMIT {DROP_BATCH}"
                )
            ]
            if not batch:
                break
            values = " ".join(f"<{iri}>" for iri in batch)
            graph.update(
                f"DELETE {{ GRAPH <{name}> {{ ?a ?p ?o }} }} "
                f"WHERE {{ VALUES ?a {{ {values} }} GRAPH <{name}> {{ ?a ?p ?o }} }}"
            )
            removed += len(batch)
        graph.remove_graph(name)
    if removed:
        graph.optimize()
        logger.info(
            "Espace de noms : %s anciens agrégats retirés (%.0f s)",
            removed,
            time.monotonic() - began,
        )
    return removed
