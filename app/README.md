# WattSlot

Code de l'application : un seul serveur, pour l'extension Home Assistant comme pour le mode Docker autonome. Guide d'utilisation : `docs/` à la racine du dépôt.

| Dossier | Contenu |
|---|---|
| `backend/` | API Python (FastAPI) : santé, connexion à Home Assistant, stockage, puis calcul et serveur MCP |
| `frontend/` | Interface React + TypeScript (Vite), compilée en fichiers statiques servis par le backend |

## Prérequis

- Python 3.11 ou plus récent.
- Node.js 22.12 ou plus récent (exigé par Vite 8 et Vitest), avec npm 11 : npm 10 échoue à résoudre les dépendances de Vitest (`npm install -g npm@11.20.0`).

## Environnement de développement

Home Assistant de test qui rejoue des journées, et l'application connectée à ce HA, sans aucune saisie : `dev/README.md`.

## Lancer en local

Backend, sur le port 8100, avec ses données dans `app/backend/data` (ignoré par git) et, en option, une connexion à un Home Assistant (variables de `app/.env.example`) :

```bash
cd app/backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS : .venv/bin/python
WATTSLOT_DATA_DIR=data .venv/Scripts/uvicorn wattslot.main:app --reload --port 8100
```

Interface, sur le port de Vite (5173), qui relaie `/api` vers le backend :

```bash
cd app/frontend
npm ci
npm run dev
```

## Installation en mode autonome

Guide d'installation : `docs/installation.md` (Docker Compose, variables d'environnement, connexion à Home Assistant).

## Image Docker

Une seule image (`app/Dockerfile`) pour l'extension HA et le mode autonome, en `linux/amd64` et `linux/arm64` : interface compilée, backend Python, Oxigraph embarqué (`pyoxigraph`). Données dans `/data` : base SQLite `wattslot.db`, magasin principal `oxigraph/` (vocabulaire, modèle de la maison) et relevés bruts `raw/AAAA-MM-JJ/`, un magasin Oxigraph par jour en heure locale de la maison.

```bash
docker build -t wattslot app
docker run --rm -p 8100:8100 --env-file app/.env -v wattslot-data:/data wattslot
```

Mode détecté au démarrage : `SUPERVISOR_TOKEN` présent (fourni par le Supervisor) → extension, connexion à HA par `ws://supervisor/core/websocket` ; sinon → autonome, connexion par `HA_URL` et `HA_TOKEN` (ou `HA_TOKEN_FILE`, fichier contenant le jeton), à défaut par la connexion enregistrée depuis l'interface (`/data/home_assistant.json`, lot 4.6 : OAuth2 de HA ou jeton saisi). La CI publie l'image sur GitHub Container Registry (`ghcr.io/<propriétaire>/<dépôt>`, étiquettes `main` et `sha-…`) après chaque merge dans `main`.

## Extension Home Assistant

Emballage dans `ha-addon/wattslot/` (`config.yaml` : ingress, accès à l'API de HA ; surveillance par le `HEALTHCHECK` de l'image sur `/api/health`, que le Supervisor suit pour relancer l'extension ; 30 s pour s'arrêter), même image que le mode autonome. Le Supervisor télécharge `ghcr.io/<dépôt>:<version de config.yaml>`.

### Versions (phase 6 ter, lot 6t.1)

Numérotation SemVer (`X.Y.Z`), la même pour l'extension, le serveur et l'interface : `python app/scripts/version.py` l'affiche, `python app/scripts/version.py X.Y.Z` la change dans `config.yaml`, `pyproject.toml`, `package.json` et `package-lock.json`, et ajoute en tête du `CHANGELOG.md` de l'extension (affiché par HA) une section avec les titres des PR fusionnées depuis la version précédente, à relire et traduire en anglais. La CI vérifie que les quatre fichiers ont la même version (`--check`).

Les fusions dans `main` publient seulement les images `main` et `sha-…` (développement, mode autonome). Une version n'est jamais republiée sous la même étiquette : sinon le Supervisor ne voit pas la mise à jour, et il faudrait désinstaller l'extension, donc perdre ses données.

**Publier une version** (workflow `.github/workflows/release.yml`) :

1. `python app/scripts/version.py X.Y.Z`, relire et traduire en anglais la section du `CHANGELOG.md` de l'extension ;
2. PR vers `main`, fusion, attendre la fin des contrôles de `main` (l'image `sha-…` du commit de fusion doit être publiée) ;
3. `git tag vX.Y.Z <commit de la fusion>` puis `git push origin vX.Y.Z`.

Le workflow vérifie que l'étiquette est sur `main` et à la version des fichiers, que la section du changelog est écrite et que l'image `X.Y.Z` n'existe pas encore ; il donne les étiquettes `X.Y.Z` et `latest` à l'image `sha-…` déjà construite et testée (rien n'est reconstruit), puis met à jour la branche `addon` (voir ci-dessous) et enfin crée la release GitHub avec la section du changelog.

**Branche `addon`** (lot 6t.2) : c'est elle que suit le Supervisor. Elle ne contient que `repository.yaml` et `ha-addon/` de l'étiquette, un commit « Version X.Y.Z » par version, jamais de push forcé, jamais de retour à une version plus ancienne. Elle est mise à jour **après** l'image : le Supervisor ne voit jamais une version dont l'image n'existe pas. Pour une version déjà publiée (rattrapage, réparation) : `gh workflow run release.yml --ref main -f tag=vX.Y.Z` (le bouton « Run workflow » de GitHub n'apparaît que pour les workflows de la branche par défaut, `main`) ; seule la branche `addon` est mise à jour, si l'image de la version existe.

En mode extension, l'application ne répond qu'au proxy d'ingress du Supervisor (`172.30.32.2`) et à la machine elle-même (`HEALTHCHECK` de l'image).

**Sauvegardes à chaud** (`backup.py`) : avant de copier le dossier de l'extension, HA lance `backup_pre` (`python -m wattslot.backup prepare`), qui appelle `POST /api/backup/prepare` ; l'application y fige une copie de SQLite (API de sauvegarde) puis du graphe (point de contrôle de RocksDB, en liens physiques) dans `/data/backup/`. Les fichiers vivants (`oxigraph`, `wattslot.db*`) et le brut (`raw`) sont exclus : HA ne sauvegarde que la copie, qui ne bouge plus ; `backup_post` (`… finish`) la supprime. Rien n'est suspendu pendant la copie. Après une restauration, l'application remet la copie en place au démarrage (base et graphe absents) ; une copie restée d'une sauvegarde interrompue est supprimée. Les deux routes ne répondent qu'à la machine elle-même (`127.0.0.1`), pas à l'ingress.

**Options** (`addon_options.py`, `translations/` de l'extension) : niveau des journaux, conservation du brut (1 à 30 jours) et des quarts d'heure (31 à 3660 jours), lus dans `/data/options.json` au démarrage en mode extension ; ils remplacent alors la conservation en base. Icône et logo : `python -m tools.addon_images` depuis `dev/`.

### Installation depuis le dépôt (dépôt privé, lot 6t.2)

Tant que le dépôt et l'image sont privés, HA suit ce dépôt comme **dépôt d'applications**, avec un jeton dans l'adresse. Depuis HA 2026.2, les « modules complémentaires » s'appellent « Applications ».

1. **Accès à l'image** : créer sur GitHub un jeton **classic** (un jeton *fine-grained* ne donne pas accès aux images) avec le seul droit `read:packages`. Dans HA : Paramètres → **Applications** → Boutique → menu ⋮ → **Registres** → ajouter le registre `ghcr.io` (sans `https://`), l'utilisateur GitHub, le jeton comme mot de passe. Sans registre, l'installation échoue avec `401 unauthorized`.
2. **Accès au dépôt** : créer un jeton **fine-grained** limité à ce seul dépôt, avec le seul droit **Contents : Read-only**, et **sans expiration** (voir l'avertissement ci-dessous).
3. **Ajout du dépôt** : Boutique → menu ⋮ → **Dépôts** → ajouter `https://<utilisateur GitHub>:<jeton du point 2>@github.com/<dépôt>#addon` (`#addon` : la branche publiée, pas `main`).
4. **Installation** : l'application « WattSlot » apparaît dans la Boutique, sous le nom du dépôt. Installer, cocher « Afficher dans la barre latérale », démarrer.
5. **Vérification** : la page affiche le mode « Extension Home Assistant », Home Assistant « connecté » et sa version.
6. **Mises à jour** : à chaque version publiée, HA propose « Mettre à jour » (Boutique → menu ⋮ → **Rechercher des mises à jour** pour ne pas attendre), avec sa sauvegarde automatique avant la mise à jour.

Procédure vérifiée le 18/10/2026 sur HA OS (lot 6t.4) : installation de la 0.7.0 depuis le dépôt, mise à jour vers la 0.8.0 par « Mettre à jour » (options dans l'onglet « Configuration »), sauvegarde partielle de l'application (Paramètres → Système → Sauvegardes) puis restauration, arrêt et redémarrage sans erreur dans le journal.

⚠️ **L'adresse du dépôt fait partie de l'identifiant de l'application.** Le Supervisor calcule l'identifiant du dépôt à partir de l'adresse exacte, jeton compris (`<empreinte>_wattslot`), et les données de l'application en dépendent. Changer de jeton, ou passer à l'adresse publique (phase 7), crée **une autre application**, sans les données de la première. D'où le jeton sans expiration, et la bascule de la production sur l'extension seulement après la phase 7 (point n° 4 de la phase 6 ter). L'adresse, donc le jeton (lecture seule, ce dépôt seul), reste visible dans la liste des dépôts de HA.

⚠️ **Sur un HA en service, ne pas enregistrer la page Maison** pour un simple essai : l'ingestion démarrerait, avec la reprise de tout l'historique de HA (1 h 25 et plus de 3 Go pour la maison de référence). Désinstaller l'application supprime ses données.

**Depuis l'installation de test en application locale** (`local_apps`, 16/10/2026) : l'application locale (`local_energy_optimizer`) et celle du dépôt sont deux applications distinctes, chacune ses données. Si la page Maison n'a pas été enregistrée sur l'application locale, il n'y a rien à garder : la désinstaller, supprimer `local_apps/wattslot`, puis installer depuis le dépôt. L'installation en application locale (copie de `ha-addon/wattslot` dans `local_apps/wattslot`, par Samba ou SSH) reste possible pour essayer une branche non publiée, mais elle ne reçoit pas les mises à jour.

## Contrôles

**Données personnelles** (lot 7.1, job « Données personnelles ») : `python dev/tools/privacy_check.py` contrôle les fichiers que `publish.txt` retient pour le dépôt public : adresses IPv4 privées (sauf le réseau interne du Supervisor), jetons, e-mails, adresses MAC, et une **liste personnelle** (prénoms, noms d'hôtes, entités de la maison de référence) qui n'est jamais dans le dépôt : secret `PRIVACY_TERMS` en CI, fichier `~/.config/wattslot/privacy-terms.txt` (ou `PRIVACY_TERMS_FILE`) en local. La sortie donne `fichier:ligne` et le numéro de la règle, jamais le texte trouvé ; une ligne légitime porte `privacy: ok` et sa raison. Exemples d'adresses dans les tests : plage de documentation `192.0.2.x`.

Les mêmes qu'en CI (`.github/workflows/v2.yml` : sur une pull request vers `main`, seuls les jobs que les fichiers modifiés concernent, avec Python 3.12 et l'image amd64 ; tous les jobs après le merge) :

```bash
cd app/backend && ruff check . && ruff format --check . && mypy && pytest
cd app/frontend && npm run lint && npm run typecheck && npm test && npm run build
```

## Ontologie

`backend/src/wattslot/ontology/` : espace de noms `https://w3id.org/wattslot/` (lot 7.1, `__init__.py`, préfixe `wattslot:` en Turtle et en SPARQL, `VOCAB` dans le code ; les données de l'ancien espace provisoire `energy-optimizer.invalid` sont migrées au démarrage par `migration.py` : maison et réglages réécrits, capteurs des relevés bruts réécrits, agrégats recalculés depuis l'historique de HA, anciens agrégats vidés en arrière-plan) ; bibliothèque « Énergie domestique » (`library/home-energy.ttl` : maison, équipements, capteurs, rôles, agrégats ; maintenue dans VocBench, phase 2 bis) et schéma de l'application (`schema.ttl` : réglages, contraintes, objectifs), IRI relatives résolues au chargement. Graphes nommés : bibliothèque, schéma, modèle de la maison, configuration.

## Conventions

- **Code et identifiants en anglais**, commentaires, documentation et messages de commit en français.
- **Aucune donnée personnelle dans le code** (adresse, nom d'hôte, nom d'appareil, identifiant d'entité de la maison de référence) : tout passe par la configuration (décision 2).
- **Versions exactes** pour toutes les dépendances (`pyproject.toml`, `package.json` et `package-lock.json`), publiées depuis au moins deux semaines au moment de leur ajout.
- **Traductions** : un catalogue JSON par langue dans `frontend/src/i18n/catalogs/`, mêmes clés et mêmes paramètres `{nom}` dans tous les catalogues (vérifié par `translate.test.ts`). Six langues (lot 5.7) : français et anglais dans le fichier principal, allemand, néerlandais, espagnol et italien chargés à la demande et « à relire » (`_meta.status`). Langue choisie par `?lang=` dans l'URL, sinon le choix mémorisé dans le navigateur, sinon la langue du navigateur, sinon l'anglais. Les textes rédigés par le serveur (explications, recommandation, avertissements, notifications) suivent `?lang=` dans les six langues (`languages.py`, catalogues `planning/locales` et `planning/locales/warnings`), le français pour une langue inconnue.
- **URL relatives** dans l'interface (`api/health`, pas `/api/health`) : derrière l'ingress de Home Assistant, l'application est servie sous un préfixe variable.
- **Interface** : voir la section suivante.

## Interface

Refaite à la phase 6 bis autour des questions de l'utilisateur, le téléphone d'abord.

- **Cinq sections**, une adresse chacune après le « # » (`src/nav/routes.ts`) : Aujourd'hui (`#/today` : le moment, la prochaine action, la journée), Planning (`#/planning` : Hier, Aujourd'hui, Demain et Semaine en agenda, « Courbes détaillées » repliées), Ma maison (`#/home` : la maison en phrases, réglages détaillés repliés), Assistant (`#/assistant` : « Mes demandes », assistant vocal), Réglages (`#/settings` : une liste, chaque réglage dans sa sous-page). Écrans experts sous « Pour aller plus loin » : `#/home/devices`, `#/home/templates`, `#/home/backup`, `#/home/graph`, `#/home/library`, `#/settings/status` (diagnostic), `#/settings/connection`. Les anciennes cibles du serveur (`home#tariff`, `settings#notification`…) mènent à leur nouvelle place.
- **Menu** (`src/nav/MainMenu.tsx`) : en bas de l'écran sous 768 px ; latéral au-delà, repliable en rail d'icônes (ouvert par défaut au-delà de 1 280 px, choix gardé dans le navigateur). Pastille d'état (problèmes du diagnostic) et « Demander un appareil » toujours à portée.
- **Thèmes** (`src/theme/themes.css`) : « Automatique » par défaut (Ivoire, ou Graphite quand le système est en sombre), Ivoire, Graphite, Océan, Prairie, Crépuscule ; choix gardé dans le navigateur et appliqué avant le premier affichage ; contrastes AA vérifiés par les tests. Police Manrope servie par l'application.
- **Composants** (`src/ui/`) : carte, bouton, ligne de réglage, interrupteur, feuille, icônes SVG, état d'un écran (chargement, vide, erreur avec « Réessayer ») ; démonstration de chacun dans chaque thème à l'adresse `#/ui`. Aucune couleur écrite en dur dans les composants (vérifié par les tests).
- **Premiers pas** : tant que la mise en route n'est pas finie, un parcours guidé en quatre écrans (connexion, appareils trouvés, contrat, premier plan) remplace l'accueil.
- **Accessibilité** : cibles de 44 px, focus visible, titres dans l'ordre, noms accessibles du menu replié ; `axe-core` passe sur les sections et sous-pages principales (`src/a11y.test.tsx`).
- **Confort gardé dans le navigateur** (`localStorage`) : langue, thème, menu replié, onglet de Planning, courbes et réglages détaillés ouverts, action marquée « C'est lancé ».
- **Cache du navigateur** (lot 7.1, `InterfaceFiles` dans `main.py`) : page d'accueil en `Cache-Control: no-cache`, revalidée à chaque visite, pour qu'une mise à jour soit vue aussitôt ; fichiers de `assets/`, dont le nom porte l'empreinte du contenu, gardés un an (`immutable`).
- **Nouvelle version** (lot 7.1, `src/nav/updates.ts`) : le navigateur lit la dernière release du dépôt public sur l'API de GitHub au chargement puis toutes les heures tant qu'un onglet est ouvert (résultat gardé une heure et partagé entre les onglets) ; si elle est plus récente, un point sur « Réglages », une ligne dans la liste des Réglages et un encadré dans État de l'application (notes de version, façon de mettre à jour selon le mode). Dépôt absent ou hors ligne : « impossible de vérifier ». Aucun appel sortant de plus côté serveur.

## Assistant (MCP)

L'application expose un serveur MCP sur `/mcp` (phase 6) : l'Assist de Home Assistant s'en sert, avec le modèle de langage choisi dans HA (Ollama sur le réseau local, ou un service en ligne), pour répondre aux questions sur le plan, les mesures et la prévision. Le plan reste calculé sans LLM. La page « Assistant » de l'interface guide le branchement et vérifie que le serveur répond.

1. **Brancher l'application** : dans HA, Paramètres › Appareils et services › Ajouter une intégration › « Model Context Protocol », avec l'adresse donnée par la page « Assistant ». En extension, c'est l'adresse de l'extension sur le réseau interne de HA (`http://<nom d'hôte de l'extension>:8100/mcp`), que seul HA Core peut joindre. En mode autonome, c'est `http://<adresse de l'application>:8100/mcp`.
2. **Agent de conversation** : un modèle qui sait appeler des outils, avec une taille de contexte d'au moins 8 192 tokens ; dans ses options, le serveur MCP de l'application comme API LLM.
3. **Prompt conseillé** : celui de la page « Assistant » (`GET /api/assistant/prompt?lang=`), à coller dans les instructions de l'agent.

Ce que l'assistant peut faire : lire le plan d'un jour et ses explications, la semaine, les mesures, la prévision, la maison et les problèmes ; une seule action, déposer une demande (« lance le lave-vaisselle au meilleur moment »), après confirmation. Il ne lance aucun calcul et ne change aucun réglage.

**Protection** : l'intégration MCP de HA n'envoie de jeton que par OAuth2 (vérifié dans son code), que l'application ne propose pas. Le serveur MCP a donc la même protection que l'interface : en extension, seul HA Core le joint ; en mode autonome, l'application ne doit être ouverte que sur le réseau local.

## Points d'accès

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/health` | Version, mode de fonctionnement (`addon` : extension HA, `standalone` : Docker autonome), état de la connexion à Home Assistant (`not_configured`, `connecting`, `connected`, `error`, avec la version de HA et la dernière erreur) |
| GET | `/api/energy/sources` | Sources du tableau Énergie de HA : production, compteurs du réseau, batteries, équipements suivis (`configured: false` si le tableau n'est pas configuré) |
| GET | `/api/home/proposals` | Rôles proposés pour les entités de la maison (tableau Énergie et registres de HA), avec les anomalies détectées ; `?refresh=true` relit HA d'abord. 503 si HA n'est pas connecté |
| GET | `/api/home` | Modèle de la maison validé (équipements, capteurs, rôles, entités HA), lu dans le graphe de la maison |
| PUT | `/api/home` | Enregistre le modèle de la maison (remplace le précédent) ; l'ingestion suit aussitôt les entités retenues. Les types propres (`types`) et le type propre d'un équipement (`custom_type`) absents de la requête sont gardés. 422 avec les anomalies du modèle (clés en double, type inconnu, type d'un autre parent) |
| GET | `/api/home/entities` | Capteurs de HA qu'on peut lier à un équipement ajouté à la main (`entity_id`, `name`, `unit`, `roles` possibles d'après l'unité : énergie, puissance, pourcentage). 503 sans HA |
| GET | `/api/home/types` | Types d'équipements : ceux de la bibliothèque qui acceptent des sous-types (`parents`) et les types propres à l'installation (`types` : `key`, `name`, `parent`) |
| POST | `/api/home/types` | Crée un type propre (`name`, `parent`) ; sa clé est tirée du nom. 422 si le parent n'est pas permis |
| PATCH | `/api/home/types/{key}` | Renomme un type propre. 404 s'il n'existe pas |
| DELETE | `/api/home/types/{key}` | Supprime un type propre. 404 s'il n'existe pas, 409 si un équipement l'a (`type_in_use`) |
| GET | `/api/configuration` | Configuration de la maison (phase 3) : pour chaque équipement du modèle de la maison, son comportement pour le calcul (`CycleBehavior`, `EnergyByDeadlineBehavior`, `RuntimeBehavior`, `StorageBehavior`, `UncontrolledBehavior`, `ProductionBehavior`, `GridBehavior`), son niveau d'automatisation et sa prise en compte par le calcul (`planned`) ; `default` : rien d'enregistré, réglages par défaut de son type ; `tariff` : tarif de la maison (`SingleTariff`, `TimeOfUseTariff`, prix de base, plages `start_hour`-`end_hour` avec leur prix et, au besoin, jours de la semaine et mois, prix de revente), `DayColorTariff` : couleurs avec leur prix de base et leurs plages, entités de la couleur du jour et du lendemain, heure de début du jour de couleur ; `DynamicTariff` : entité de prix, facteur d'unité ; revente fixe ou par entité ; `null` : prix unique par défaut de 0,25 €/kWh ; `battery` : puissances de charge et de décharge (W, `null` : 0,5 C), plancher (%), plage active, charge complète au moins tous les N jours (`null` : jamais) ; `null` : 0,5 C, 10 %, toute la journée, 7 jours ; par équipement en durée à placer, `runtime` : vitesses (`name`, `kw` ; vide : une seule, mesurée), heures minimales et jours sautables par saison (`summer`, `mid_season`, `winter`), démarrages par jour ; par équipement en besoin d'énergie, `energy` : énergie `energy_kwh`, `earliest_hour`, échéance `deadline_hour` (exclue), `max_kw`, `steps` (tout ou rien), `daily` (sinon quand une tâche le demande) ; `null` : traité comme un cycle à démarrer ; par équipement placé (cycle, besoin, durée), `constraints` : contraintes horaires (`kind` : `forbidden` de `start_hour` à `end_hour` exclue, à cheval sur minuit si `start_hour > end_hour`, `not_before` `start_hour`, `finish_before` `end_hour` ; `hard` : jamais violée, sinon souple) ; par cycle à démarrer, `after` (clé de l'équipement dont le cycle doit finir avant, le même jour) et `max_delay_days` (tolérance de report d'une tâche en attente, `null` : 2 jours) ; `recurrence` (`rule` RFC 5545, `start` : semaine de départ d'un intervalle hebdomadaire ; les tâches récurrentes de HA de l'équipement sont alors ignorées) ; dans `battery`, `floor_ranges` : plages (`start_hour`, `end_hour` exclue, `percent`) où le plancher est plus haut ; `objective` : objectif du calcul (`preset` : `cost`, `autonomy`, `self_consumption`, `co2` avec `co2_entity`, entité d'intensité carbone du réseau, ou `custom` avec `weights` : `cost`, `grid_import`, `grid_export`, `co2`, `battery` en équivalent euros) ; `null` : le réglage du calcul |
| GET | `/api/configuration/tariff-proposal` | Tarif proposé d'après les prix du tableau Énergie de HA : prix dynamique si une entité de prix est déclarée, prix unique s'il y a un prix fixe, revente fixe ou par entité ; `null` sans prix déclaré. 503 sans HA |
| PUT | `/api/configuration` | Enregistre la configuration ; 422 avec les anomalies (`code`, `device`, `params`) si elle n'est pas valide |
| GET | `/api/configuration/task-rules-proposal` | Règles reprises des descriptions JSON des tâches de la liste de HA, par équipement : `recurrence` (règle, échéance comme semaine de départ), `after` (équipement à suivre) ; à valider dans l'onglet Maison. 503 sans HA |
| GET | `/api/profiles` | Profils d'exemple (nom, description) : maison de référence et ses variantes (sans batterie, sans piscine, Tempo, prix dynamique, véhicule électrique, deux lave-vaisselle, hémisphère sud) |
| GET | `/api/profiles/{name}` | Fichier d'un profil, au format d'export : à importer par `/api/configuration/import`. 404 pour un profil inconnu |
| GET | `/api/configuration/export` | Modèle de la maison et configuration en un fichier JSON versionné (`format` : `wattslot/home`, l'ancien `energy-optimizer/home` accepté, `version`, `home`, `configuration`), à télécharger |
| GET | `/api/configuration/export.ttl` | Graphes de la maison et de sa configuration en Turtle, pour l'ontologie |
| POST | `/api/configuration/import` | Importe un tel fichier : vérifié (format, version migrée, modèle, anomalies de la configuration), entités inconnues de HA signalées (`unknown_entities`) sans bloquer ; valide, il remplace le modèle de la maison et la configuration (`applied`). `?dry_run=true` : vérification seule. 422 avec les anomalies |
| POST | `/api/configuration/validate` | Anomalies d'une configuration proposée, sans l'enregistrer |
| GET | `/api/ingestion` | État de l'ingestion en temps réel : entités suivies (rôle, dernière valeur, relevés reçus et retenus), relevés écrits, file d'attente, dernière erreur, journées stockées, relevés repris de HA après une coupure (`backfilled`, `last_backfill_at`) |
| GET | `/api/aggregation` | État de l'agrégation : fin de la dernière période calculée par période (`complete_until`), agrégats écrits, dernière erreur ; reprise de l'historique de HA (`history` : entités reprises, en attente, sans statistiques, agrégat repris le plus ancien par période) |
| GET | `/api/planning/history` | Entrées du calcul tirées de l'historique pour un jour (`?day=`, aujourd'hui par défaut) : ligne de base par heure (kWh), meilleure production des 30 derniers jours, historique récent (dernière charge complète, jours sans filtration), rendements de la batterie par sens sur 30 jours, profil de cycle de chaque équipement (énergie et durée médianes, forme, nombre de journées lues dans le brut ou au quart d'heure), cycles réels du jour. 503 sans HA |
| GET | `/api/settings/planning` | Réglages du calcul : objectif (`cost` coût d'abord, `import` soutirage d'abord, `self_consumption` autoconsommation d'abord ; remplacé par celui de la configuration dès qu'il y est réglé, lot 3.6), liste de tâches de HA (`todo_entity`), entités de prévision de repli (`forecast_entities`, attribut `forecast` au format de Helios), calculs automatiques (`scheduler_enabled`, `true` par défaut) et minute du calcul horaire (`run_minute`, 59 par défaut), période de relecture des données réelles du jour entre deux calculs (`actual_refresh_minutes`, 15 par défaut, aux minutes multiples de la période, sauf à moins de 5 min du calcul horaire ; 0 : aucune), service de notification de la recommandation après chaque calcul planifié (`notify_service`, « notify.mobile_app_… », aucun par défaut) et sa langue (`notify_language`, une des six langues) ; remplacés par `/api/settings/notifications` dès qu'il est enregistré (lot 5.6) ; ancien dashboard servi ou non (`legacy_dashboard`, `true` par défaut, lot 5.8) |
| PUT | `/api/settings/planning` | Modifie ces réglages (page « Réglages » de l'interface, lot 4.2) |
| GET | `/api/settings/choices` | Choix proposés par la page « Réglages », lus dans HA : listes de tâches (`todo.*`), services de notification (`notify.*`, par `get_services`), entités de prévision au format de Helios ; `connected` faux et listes vides sans HA |
| GET | `/api/planning/input` | Entrée du calcul assemblée pour un jour (`?day=`, aujourd'hui par défaut), **au format de la v1** : comparaison croisée avec les entrées capturées de la v1. 503 sans HA, 409 sans prévision solaire |
| POST | `/api/planning/run` | Calcule le plan du jour (fusionné avec le précédent de la journée), puis demain et l'horizon ; un calcul à la fois ; renvoie les durées et les erreurs éventuelles. 503 sans HA, 409 sans prévision solaire |
| POST | `/api/planning/actual` | Bouton « Rafraîchir » : données réelles du jour (SoC, production, échanges réseau, consommation, cycles réels des équipements, de la piscine et de la batterie) relues sur le brut et gardées dans le plan du jour, sans calcul ; calcul complet si ce plan porte encore sur la veille. 503 sans agrégation |
| POST | `/api/planning/notify` | Notification d'essai de la recommandation du plan du jour, envoyée tout de suite par son appareil (gardée pour l'interface d'avant le lot 5.6, comme `/api/notifications/recommendation/test`) ; renvoie le texte. 503 sans HA, 409 sans appareil (`no_notify_service`) ou sans plan (`no_plan`) |
| GET | `/api/settings/notifications` | Notifications activables (lot 5.6) : appareil commun (`service`, « notify.… »), langue (`language`), et pour chacune (`recommendation`, `device_now`, `plan_gap`, `battery_full`, `forecast_drop`) activation, appareil propre, heures de silence (`quiet_hours` `{start, end}`, sautées, pas différées) ; la recommandation a son rythme (`cadence` : `every_run` comme la v1, `when_changed`, `daily` à `daily_at`). Sans réglage enregistré : `notify_service` et `notify_language` des réglages du calcul. Rien d'activé par défaut |
| PUT | `/api/settings/notifications` | Modifie ces réglages |
| POST | `/api/reminders` | « Me le rappeler » (lot 6b.3) : rappel du jour pour un appareil à cycle encore à lancer (`device`, nom dans le plan du jour) ; envoyé une fois, à l'heure de début que lui donne le plan du moment (il suit donc un déplacement), par le service de la notification `device_now`, même désactivée ; fermé sans envoi si l'appareil est lancé avant. 404 sans plan du jour, 422 `not_planned` pour un appareil qui n'est pas à venir |
| DELETE | `/api/reminders/{device}` | Retire le rappel du jour d'un appareil ; 404 s'il n'y en a pas ou s'il est parti |
| POST | `/api/notifications/{kind}/test` | Envoi d'essai d'une notification, tout de suite, sans heures de silence ni rythme, sans le noter dans le journal des envois ; hors recommandation, la situation du moment s'il y en a une, sinon un exemple, marqués « [Essai] » ; mêmes codes que `/api/planning/notify` |
| POST | `/mcp` | Serveur MCP (lot 6.1, Streamable HTTP, sans état, réponses JSON) pour l'intégration « Model Context Protocol » de HA : outils de lecture du plan, de la semaine, des mesures, de la prévision, de la maison et des problèmes, et une action : déposer une demande (`request_device`, lot 6.2). En extension, seul HA Core y accède hors de l'ingress |
| GET | `/api/assistant/connection` | Adresse du serveur MCP à donner à l'intégration MCP de HA (lot 6.3) : `mcp_url` en extension (réseau interne de HA), aucune en mode autonome (la page « Assistant » reprend l'adresse du navigateur) |
| GET | `/api/assistant/prompt` | Prompt système conseillé pour l'agent de conversation de HA (`?lang=`, une des six langues ; lot 6.2) |
| GET | `/api/settings/dashboard` | Disposition du dashboard (lot 5.5) : pour chaque vue (`yesterday`, `today`, `tomorrow`, `week`), ordre complet du catalogue et cartes masquées ; indicateur mis en avant (`null` : celui de l'objectif) et indicateurs masqués ; `default` vrai sans personnalisation |
| PUT | `/api/settings/dashboard` | Enregistre la disposition (cartes inconnues ou en double refusées) |
| DELETE | `/api/settings/dashboard` | « Revenir à la disposition par défaut » |
| GET | `/api/planning/status` | Planificateur des calculs (chaque heure à `run_minute`, bascule à 0 h 01, relecture des données réelles du jour toutes les `actual_refresh_minutes` sans calcul, comme le bouton « Rafraîchir ») : prochain calcul, dernier calcul, dernier réussi et son bilan, dernière erreur, dernière relecture des données réelles et sa durée (`last_actual_at`, `last_actual_seconds`) |
| GET | `/api/planning/plan` | Plan gardé en base, au format de la v1 : `?view=today` (défaut), `yesterday`, `tomorrow`, `horizon`. Avec ses `indicateurs` (lot 3.6) et, pour aujourd'hui et demain, l'`explication` de chaque élément (lot 3.7 : `raisons`, codes et paramètres, et `alternative` d'un cycle : `debut_min`, `ecart_cout_eur`, `ecart_soutirage_kwh`). 404 avant le premier calcul |
| GET | `/api/aggregates` | Agrégats d'une entité suivie : `?entity_id=…&start=…` (heure avec fuseau), `end` (un jour après `start` par défaut), `period` (`PT1H` par défaut, ou `PT15M`) ; énergie (kWh) pour un compteur ; moyenne, maximum et valeur en fin de période (`last`) pour les autres mesures |
| GET | `/api/views/{yesterday\|today\|tomorrow}` | Vue d'un jour pour le nouveau dashboard (lot 5.1) : en-tête (calcul, dernier relevé), 24 heures prévues et réelles (production, consommation, achat, surplus, charge, décharge, SoC, heures creuses), résumé de fin de journée, prévision du premier calcul, production recalée ; pour Aujourd'hui (lot 6b.3), « En ce moment » (`now` : puissances moyennes du dernier quart d'heure clos, niveau de la batterie, phrase du moment) et prochain appareil à lancer (`next_action`, avec `reminder` : rappel posé, et `can_remind` : service de notification réglé) ; 404 sans plan |
| GET | `/api/views/versions` | Heure (horodatage) du dernier calcul de chaque vue (`yesterday`, `today`, `tomorrow`, `week`) : la page recharge la sienne quand elle change |
| GET | `/api/views/week` | Vue Semaine (lot 5.1) : aujourd'hui puis les 7 jours de l'horizon (carte de chaque jour, points horaires bout à bout, plancher de la batterie, dernier relevé) ; 404 sans horizon |
| GET | `/api/connection` | Connexion à HA (lot 4.6) : mode, source (`supervisor`, `env`, `saved`, aucune), adresse et méthode (`oauth`, `token`) d'une connexion enregistrée, état ; jamais de jeton |
| POST | `/api/connection/token` | Jeton longue durée `{url, token}`, vérifié auprès de HA puis enregistré ; l'application redémarre ; 400 `token_refused` ou `unreachable`, 409 en mode extension ou si l'environnement fixe la connexion |
| POST | `/api/connection/oauth` | `{url, client_id}` (adresse de l'application vue du navigateur) : adresse de la page de connexion de HA |
| GET | `/auth/callback` | Retour de HA : code échangé contre les jetons, enregistrés ; redirige vers l'application (`?connection=ok`, `failed` ou `expired`) et redémarre |
| DELETE | `/api/connection` | Déconnexion : jeton de rafraîchissement révoqué auprès de HA, connexion oubliée, redémarrage |
| GET | `/api/requests` | Demandes déclarées dans l'application (lot 4.5) : ouvertes, puis closes depuis 7 jours (`device`, `latest`, `status` : `open`, `done`, `cancelled`, `launched_on`) |
| POST | `/api/requests` | Demande `{device, latest?}` ; une demande ouverte pour le même équipement change seulement de date ; 422 pour un équipement qu'on ne peut pas demander |
| POST | `/api/requests/{id}/done` | Demande faite (à la main) |
| DELETE | `/api/requests/{id}` | Demande annulée |
| GET | `/api/requests/devices` | Équipements qu'on peut demander : cycles à démarrer et besoins d'énergie |
| GET | `/api/diagnostic/problems` | Ce qui ne va pas (lot 4.8), les plus graves d'abord : `code`, `severity` (`blocking`, `degraded`, `watch`), `params` (noms d'équipements), `target` (page où agir) ou `doc` (documentation de HA, tickets du projet) |
| GET | `/api/diagnostic/report` | Rapport anonymisé à joindre à un ticket : versions, état des composants, problèmes, maison et configuration sans identifiant d'entité, nom, position ni adresse |
| GET | `/api/forecast/comparison` | Prévision Open-Meteo des 7 derniers jours comparée à la production mesurée (lot 4.4) : `days` (`day`, `forecast_kwh`, `measured_kwh`), `ratio` (mesuré / prévu) ; `available` faux et `reason` (`no_panels`, `no_position`, `unavailable`) sinon |
| GET | `/api/templates` | Modèles prêts à l'emploi (lot 4.3) : clé, nom et description par langue, type de tarif, équipements de la maison que chacun réglerait ; le modèle Tempo d'abord si HA a une entité Tempo |
| POST | `/api/templates/{clé}/preview` | Ce que le modèle changerait (`changes` : équipement par équipement, puis tarif, objectif, batterie ; `issues` : ce qui manque), sans rien enregistrer. Corps facultatif : entités du tarif (`color_entity`, `color_tomorrow_entity`, `price_entity`, `export_entity`) |
| POST | `/api/templates/{clé}/apply` | Applique le modèle à la configuration (mêmes entités) ; 422 avec les anomalies, 404 pour un modèle inconnu |
| GET | `/api/setup` | Mise en route : étapes vers un premier plan (`key`, `state` : `done`, `todo`, `waiting`, `blocked`, `not_applicable` ; `required` ; `reason` et `params` ; `target` : page de l'interface où y remédier), et `ready` quand toutes les étapes indispensables sont faites |
| GET | `/api/diagnostic` | Tout l'état en une réponse, pour la page Diagnostic : ingestion (avec les relevés écrits aujourd'hui par entité), agrégation, maintenance et volumes sur disque, planificateur des calculs, mémoire du processus et octets écrits sur disque depuis son démarrage (`started_at`, `written_bytes`, Linux), anomalies de configuration du tableau Énergie (`null` si HA n'est pas connecté) |
| GET | `/api/settings/retention` | Durées de conservation en jours : `raw_days` (3), `quarter_days` (35, au moins 31), `hour_days` (sans limite : `null`, sinon au moins 366) |
| PUT | `/api/settings/retention` | Modifie ces durées, appliquées à la prochaine maintenance |
| GET | `/api/maintenance` | Maintenance nocturne (3 h 30, heure locale) : prochaine exécution, dernier bilan (journées de brut supprimées ou gardées faute d'agrégation complète, agrégats supprimés, durée), volumes sur disque (brut, magasin principal, base) |
| POST | `/api/maintenance/run` | Lance la maintenance tout de suite et renvoie son bilan |
| GET | `/` | Interface compilée (image Docker) |
