# Atelier VocBench de la bibliothèque « Énergie domestique »

VocBench 3 est l'atelier où les mainteneurs du projet font évoluer la bibliothèque du domaine (décision du 14/10/2026). Il est installé **côté projet seulement**, dans le homelab, jamais chez les utilisateurs. La bibliothèque publiée est un fichier du dépôt, `app/backend/src/wattslot/ontology/library/home-energy.ttl`, livré avec l'application : l'atelier n'a aucun lien avec les installations.

Lot 2b.3.

## Installation (une fois)

1. **LXC** Debian dans le homelab, 2 Go de mémoire pour commencer (à ajuster après la mesure ci-dessous), Java 17 (`openjdk-17-jre-headless`).
2. **VocBench 3** : distribution complète, à télécharger depuis la [page officielle](https://bitbucket.org/art-uniroma2/vocbench3/downloads) et à installer suivant le [manuel d'administration](https://vocbench.uniroma2.it/doc/sys/). Aucune image Docker officielle n'est publiée ; la distribution autonome est la voie documentée.
3. **Mémoire** : `JAVA_MIN_MEM=256M` et `JAVA_MAX_MEM=1024M` (variables du manuel d'administration, dans `setvars.in.sh` ou l'environnement). Pas de GraphDB : stockage RDF4J local.
4. **Démarrage** au boot (service systemd lançant le script de démarrage de la distribution), port 1979 ; interface sur `http://<lxc>:1979/vocbench3`.
5. **Premier utilisateur** : le premier compte enregistré est l'administrateur.

Aucun secret n'est versionné : le compte VocBench reste dans le LXC.

## Projet de la bibliothèque (une fois)

1. **Créer le projet** `home-energy`, modèle OWL, stockage RDF4J local (« native store »), historique activé :
   - URI de base : `https://w3id.org/wattslot/ontology/library/home-energy` ;
   - espace de noms par défaut : `https://w3id.org/wattslot/ontology#`.

   Espace de noms de WattSlot depuis le lot 7.1 (avant : `energy-optimizer.invalid`, provisoire) ; un projet VocBench créé avec l'ancien espace est à recréer.
2. **Miroirs des ontologies importées** : sur un poste avec le dépôt, `python dev/tools/fetch_imports.py` télécharge SAREF core 4.1.1, SAREF4ENER 2.1.1, SOSA et SSN dans `ontology/imports/` et vérifie leurs empreintes. Dans VocBench (espaces de noms et imports du projet), ajouter chacun comme import depuis un fichier local, sous son IRI :

   | Fichier | IRI importée |
   |---|---|
   | `saref-core.ttl` | `https://saref.etsi.org/core/` |
   | `saref4ener.ttl` | `https://saref.etsi.org/saref4ener/` |
   | `sosa.ttl` | `http://www.w3.org/ns/sosa/` |
   | `ssn.ttl` | `http://www.w3.org/ns/ssn/` |

3. **Charger la bibliothèque** (gestion des données du projet, chargement) : le fichier `library/home-energy.ttl` du dépôt, en Turtle, avec l'**IRI de base `https://w3id.org/wattslot/ontology`** : le fichier écrit ses IRI en relatif, résolues avec cette base comme le fait l'application.
4. **Vérifier l'aller-retour** : exporter tout de suite (voir plus bas) et reprendre l'export. Le script doit annoncer « 0 triplets ajoutés, 0 retirés » et `git diff` doit être vide : c'est le critère du lot.
5. **Mesurer la mémoire** du processus Java une fois le projet ouvert (`ps -o rss,cmd -C java`, ou la mémoire du LXC). Le noter dans la PR : l'estimation est entre 512 Mo et 1 Go.

## Faire évoluer la bibliothèque

1. Modifier dans VocBench : classes, propriétés, libellés français et anglais, commentaires. Les contrôles de qualité (ICV) et l'historique servent à relire avant de publier.
   Les formes SHACL de la bibliothèque (`library/home-energy.shapes.ttl`) peuvent être chargées dans le projet pour la validation SHACL de VocBench ; la CI les applique de toute façon (`tests/test_shapes.py`).
2. **Exporter** le projet en Turtle (gestion des données du projet, export), **sans** les ontologies importées.
3. Sur un poste avec le dépôt, dans une branche :

   ```bash
   python dev/tools/library.py chemin/vers/export.ttl
   ```

   Le script ne garde que les termes de la bibliothèque, réécrit le fichier sous sa forme normalisée (IRI relatives, ordre fixe) et compte les triplets ajoutés et retirés. Le diff ne montre alors que ce qui a changé.
4. Pull request, comme pour le code : la CI vérifie que le fichier est normalisé, que chaque terme écrit ou lu par l'application existe encore, que la reprise de la v1 est complète, et qu'aucune donnée de la v1 n'y figure.

Un terme ajouté ou renommé que le code utilise demande aussi un changement du code, dans la même PR.

## Plus tard

- **Export par l'API** de VocBench (Semantic Turkey), sans passer par l'interface : l'API n'est pas décrite en OpenAPI, et les appels de connexion et d'export seront relevés dans les échanges du navigateur avant d'être automatisés.
