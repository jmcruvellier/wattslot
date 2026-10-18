"""Ontologie de l'application : vocabulaire « Énergie domestique » et modèle de la maison.

Espace de noms de WattSlot (lot 7.1 de la phase 7), sous ``w3id.org``, service gratuit
d'identifiants permanents : déclaré ici seulement. Le vocabulaire (``library/home-energy.ttl``) et
le schéma (``schema.ttl``) n'écrivent aucune IRI absolue : ils sont chargés avec ``BASE`` comme IRI
de base. Préfixe ``wattslot:`` dans le Turtle et le SPARQL, ``VOCAB`` dans le code.
"""

BASE = "https://w3id.org/wattslot/ontology"
VOCAB = f"{BASE}#"
HOME = "https://w3id.org/wattslot/home/"

# Bibliothèque du domaine (library/home-energy.ttl) et schéma de l'application (schema.ttl),
# chacun dans son graphe nommé, remplacé en entier à chaque démarrage (lot 2b.1).
GRAPH_LIBRARY = f"{BASE}/graph/library/home-energy"
GRAPH_SCHEMA = f"{BASE}/graph/schema"
GRAPH_HOME = f"{BASE}/graph/home"
GRAPH_CONFIGURATION = f"{BASE}/graph/configuration"

# Espace de noms provisoire d'avant le renommage en WattSlot (lot 7.1) : ses graphes sont migrés
# au démarrage (``ontology/migration.py``).
LEGACY_BASE = "https://energy-optimizer.invalid/ontology"
LEGACY_HOME = "https://energy-optimizer.invalid/home/"
