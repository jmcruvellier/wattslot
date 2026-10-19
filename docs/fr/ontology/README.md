# Ontologie de WattSlot

*[English version](../../ontology/README.md)*

WattSlot enregistre votre maison dans un graphe RDF. Son vocabulaire a des adresses permanentes sous `https://w3id.org/wattslot/`. Chaque adresse renvoie ici, ou vers le fichier Turtle quand un client demande `text/turtle`.

| Adresse | Ce que c'est | Turtle |
|---|---|---|
| `https://w3id.org/wattslot/ontology#…` | Toutes les classes et propriétés de WattSlot (préfixe `wattslot:`) | [ontology.ttl](../../ontology/ontology.ttl) |
| `https://w3id.org/wattslot/ontology/library/home-energy` | Bibliothèque « Énergie domestique » : la maison, les équipements, les capteurs et leurs rôles, les grandeurs, les agrégats des relevés | [home-energy.ttl](../../ontology/home-energy.ttl) |
| `https://w3id.org/wattslot/ontology/schema` | Le schéma de l'application : ce qu'elle enregistre de vos réglages (comportement des équipements, tarif, batterie, contraintes, récurrences, objectif) | [schema.ttl](../../ontology/schema.ttl) |
| `https://w3id.org/wattslot/home/…` | Les équipements et capteurs de votre maison. Ils n'existent que dans votre installation, jamais en ligne | — |

La bibliothèque s'appuie sur [SAREF](https://saref.etsi.org/core/), [SAREF4ENER](https://saref.etsi.org/saref4ener/), [SOSA et SSN](https://www.w3.org/TR/vocab-ssn/). Les libellés sont en anglais et en français.

## Pour les développeurs

Ces fichiers sont générés depuis ceux de l'application (`app/backend/src/wattslot/ontology/`), dont les adresses sont relatives. Après une modification de ceux-ci, lancer :

```bash
python dev/tools/ontology_files.py
```

Les tests de `dev/` échouent quand les fichiers d'ici ne suivent plus. Les redirections de w3id sont dans [`dev/w3id/`](../../../dev/w3id/).
