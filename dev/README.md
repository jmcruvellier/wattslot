# Environnement de développement

Un Home Assistant de test qui rejoue des journées réalistes, et l'application v2 en mode autonome connectée à ce HA. Sert au développement sans le homelab, aux tests d'intégration de la CI et, plus tard, aux contributeurs.

Prérequis : Docker avec Docker Compose.

Pendant la bêta publique : tri des retours, étiquettes et réponses types dans [beta.md](beta.md).

## Démarrer

Depuis la racine du repo :

```bash
docker compose -f dev/docker-compose.yml up -d --build
```

| Service | Rôle | Adresse |
|---|---|---|
| `homeassistant` | HA de test (version figée), configuration de `dev/homeassistant/configuration.yaml` | http://localhost:8123 (compte `dev` / `dev-password`, modifiables par `DEV_HA_USERNAME` et `DEV_HA_PASSWORD`) |
| `bootstrap` | Amorçage sans saisie, puis s'arrête : compte, jeton longue durée (volume `shared`), fuseau Europe/Paris, unités, liste de tâches « Agent », tableau Énergie | — |
| `app` | Application v2 en mode autonome, connectée au HA de test par le jeton de l'amorçage (`HA_TOKEN_FILE`) | http://localhost:8100 |

Ce HA de test n'est joignable que depuis le poste : son compte n'est pas un secret.

## Rejouer une journée

```bash
docker compose -f dev/docker-compose.yml run --rm simulator                       # temps réel, à partir de l'heure de HA
docker compose -f dev/docker-compose.yml run --rm simulator --speed 60 --start 08:00
docker compose -f dev/docker-compose.yml run --rm simulator --day donnees/journee-couverte.json
```

Options : `--day` (fichier de `dev/donnees/`), `--speed` (secondes simulées par seconde, 1 = temps réel), `--step` (pas de simulation en secondes, 60 par défaut), `--start` et `--end` (HH:MM).

Le simulateur écrit les entités de la maison simulée (`dev/tools/home.py`) par l'API REST de HA : production, consommation de la maison, réseau (puissance, compteurs de soutirage et d'injection), batterie (puissance, état de charge, compteurs) et quatre équipements (puissance et compteur d'énergie). Les compteurs sont `total_increasing` : HA en tire des statistiques, comme d'une vraie intégration. La batterie, en autoconsommation, charge le surplus et couvre le déficit dans la limite de son plancher.

Les états sont horodatés par HA à leur réception : en accéléré, une journée simulée occupe moins de temps dans l'historique.

## Journées

`dev/donnees/*.json`, générées par `python dev/donnees/generer_journees.py` à partir d'une journée type anonymisée des tests du serveur (`app/backend/tests/fixtures/days/`, profils d'énergie seulement) :

| Fichier | Contenu |
|---|---|
| `journee-ensoleillee.json` | Production et consommation de base heure par heure, chauffe-eau, lave-linge, sèche-linge, lave-vaisselle (énergie et forme mesurées des cycles), batterie de 5,43 kWh |
| `journee-couverte.json` | Même journée, production à 30 % |
| `journee-sans-batterie.json` | Journée ensoleillée sans batterie |

## Contrôler

```bash
docker compose -f dev/docker-compose.yml --profile check run --rm check
```

Vérifie les entités simulées et la liste de tâches dans HA, la connexion de l'application et sa lecture du tableau Énergie (`/api/energy/sources`). La CI (`.github/workflows/v2.yml`, job « Intégration ») démarre l'environnement, simule 10h-12h de la journée ensoleillée en accéléré, puis lance ce contrôle.

Tests de la physique simulée (bilan d'énergie, énergie des cycles, plancher de la batterie), sans Docker :

```bash
cd dev && python -m pytest tools/tests
```

## Captures de la documentation

Les captures de `public/docs/images/` (lot 7.2) viennent d'une démonstration calculée par le serveur, sans Docker : une maison synthétique (`tools/demo_home.py`) simulée sur 31 jours, le vrai calcul chaque heure, puis l'application servie avec l'heure figée au 10 juin 2026 à 14 h 30 (`tools/demo.py`). Rien ne vient de la maison de référence.

Prérequis : l'interface construite (`npm run build` dans `app/frontend`), l'environnement du serveur (`pip install -e app/backend`) et, dans un autre environnement ou le même, Playwright et Pillow :

```bash
pip install -r dev/requirements-screenshots.txt
python -m playwright install chromium
```

Puis, depuis `dev/` (environ 5 minutes par langue, dont 4 de génération) :

```bash
python -m tools.screenshots
```

Le serveur tourne avec le Python de `app/backend/.venv` s'il existe, sinon celui passé par `--python`. Autres options : `--language en|fr` (une langue), `--only <nom>` (une capture, nom de `SHOTS`), `--reuse` (données déjà générées gardées, captures seules), `--data` (dossier des données, dossier temporaire du système par défaut). Pour parcourir la démonstration dans un navigateur :

```bash
python -m tools.demo generate --language fr --data /tmp/wattslot-demo/fr
python -m tools.demo serve --data /tmp/wattslot-demo/fr --port 8100
```

(avec `PYTHONPATH` sur `app/backend/src` et `dev/`, ce que fait `tools.screenshots`). L'heure du serveur est figée, pas celle du navigateur.

### Maison en triphasé

`generate --three-phase` simule la même maison raccordée en triphasé (`demo_home.ThreePhaseHouse`), pour essayer le calcul par phase sans installation réelle :

- le toit en deux installations solaires, sur les phases 2 et 3, chacune avec une batterie de 5 kWh qui ne compense que sa phase ;
- rien sur la phase 1, qui porte la moitié de la consommation de base, le chauffe-eau, le lave-linge et le lave-vaisselle ; le sèche-linge sur la phase 3 ;
- un compteur de soutirage et d'injection par phase, en plus de celui du total, qui additionne les phases ; puissance souscrite de 9 kVA, soit 3 kVA par phase.

```bash
python -m tools.demo generate --language fr --three-phase --data /tmp/wattslot-demo/tri
python -m tools.demo serve --data /tmp/wattslot-demo/tri --port 8100
```

Elle ne sert pas aux captures de la documentation.

## Banc d'essai de l'assistant

`dev/tools/assistant_bench.py` pose les 18 questions de la suite de test de l'assistant à des modèles locaux d'Ollama, plusieurs fois chacune, avec les outils du serveur MCP d'une installation de WattSlot (sans Open WebUI). Il ne dépend que de la bibliothèque standard de Python.

```bash
python dev/tools/assistant_bench.py --wattslot http://192.0.2.10:8100 --ollama http://192.0.2.20:11434 --models qwen3,lfm3 --runs 3
```

- **Profils** (`dev/tools/assistant_bench_models.json`) : étiquette Ollama, réflexion et options de chaque modèle, comme ses réglages dans Open WebUI.
- **Options** : `--questions 6,12,17` (scénarios à jouer ; `13-15` pour la conversation sur trois tours), `--runs`, `--lang`, `--prompt-file` (au lieu du prompt conseillé de l'application).
- **Variantes** : `--variants variantes.json` remplace côté banc des descriptions d'outils ou le prompt, pour comparer des formulations sans reconstruire l'image. Chaque variante est une colonne du résumé, à côté de la formulation « actuelle » du serveur, et les variantes alternent à chaque essai :

  ```json
  {"courte": {"tools": {"get_forecast": "Forecast of a day."}},
   "rappel": {"prompt_append": "Pour une date future, consulte la prévision."}}
  ```

  `prompt` remplace le prompt entier, `prompt_append` l'allonge ; un outil inconnu arrête le banc avant le premier tour.
- **Aucune demande déposée** : une confirmation de `request_device` n'est pas transmise (sauf `--allow-requests`) et compte comme un défaut grave.
- **Rapport** dans `dev/tools/.bench/` (ignoré par git, les réponses citent les équipements de la maison) : un résumé Markdown, une pastille par essai et la durée médiane, le total des pastilles, puis chaque réponse avec ses outils et la durée de son dernier passage (celle du panneau ⓘ d'Open WebUI, qui ne compte pas les passages avant les outils) ; le détail en JSON Lines. Les pastilles ne relèvent que les défauts visibles (aucun outil, nom technique, marqueur, date brute, réponse en anglais, réponse vide) : le fond se juge à la lecture.

## Repartir de zéro

```bash
docker compose -f dev/docker-compose.yml down -v
```

Supprime HA, son compte, le jeton et les données de l'application ; l'amorçage refait tout au prochain démarrage.
