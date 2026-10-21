<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/banner-fr-dark.svg">
    <img src="docs/images/banner-fr-light.svg" alt="WattSlot, bêta : le bon moment pour lancer vos appareils, avec ou sans panneaux solaires." width="100%">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/sponsors/jmcruvellier"><img src="docs/images/support-github-sponsors.svg" alt="Soutenir WattSlot sur GitHub Sponsors" height="40"></a>
  &nbsp;
  <a href="https://ko-fi.com/jmcruvellier"><img src="docs/images/support-ko-fi.svg" alt="Soutenir WattSlot sur Ko-fi" height="40"></a>
</p>

*[English version](README.md)*

**WattSlot trouve le bon créneau pour lancer vos appareils**, pour consommer votre propre électricité solaire ou les heures les moins chères de votre contrat. Il lit votre maison dans Home Assistant, planifie la journée et la semaine, et vous dit quoi lancer et quand : il recommande, vous décidez.

## Pour qui ?

- **Pas besoin de panneaux solaires ni de batterie.** Un contrat dont le prix change selon l'heure suffit : heures creuses, jours de couleur (comme Tempo d'EDF) ou prix dynamiques. Avec des panneaux ou une batterie, WattSlot tient compte en plus du soleil et de la charge.
- **Pour tout le monde.** Une fois installé, les écrans du quotidien parlent en clair : ni formule, ni YAML, rien de technique à apprendre pour l'essentiel des fonctions.
- **Léger.** Il tourne comme application dans Home Assistant (une publication dans la boutique officielle est prévue), ou sur un hôte séparé avec Docker pour ceux qui préfèrent.

<p align="center">
  <img src="docs/images/fr/today-phone-light.png" alt="Aujourd'hui, sur un téléphone" height="360">
  &nbsp;
  <img src="docs/images/fr/planning-desktop-light.png" alt="Planning, sur un ordinateur" height="360">
</p>

## Fonctions

- **Lit votre maison dans Home Assistant** : le tableau Énergie donne la production solaire, le réseau, la batterie et les appareils suivis ; l'historique vient des statistiques. Rien à saisir pour commencer.
- **Plan du jour et horizon de sept jours** : quand lancer chaque appareil, quand charger ou décharger la batterie, d'après la prévision solaire et vos prix (prix unique, heures creuses, jours de couleur, prix dynamiques lus dans une entité).
- **Votre maison, vos règles** : comportement des appareils, plages horaires, récurrences, réglages de la batterie, et ce qu'il faut optimiser (coût, autoconsommation, achat au réseau, CO₂). Modèles prêts à l'emploi, sauvegarde et partage.
- **Fait pour tous les jours** : Aujourd'hui, Planning, Courbes, Ma maison, Assistant, Réglages. Pensé d'abord pour le téléphone, cinq thèmes avec clair et sombre automatiques, six langues.
- **Demandes et rappels** : demandez un appareil depuis l'application ou depuis l'Assist de Home Assistant, soyez prévenu au bon moment.
- **Des données fiables** : WattSlot vérifie vos capteurs, signale les mesures aberrantes et vous laisse les corriger, pour qu'une mauvaise mesure ne gâche pas le reste.
- **Assistant (facultatif)** : un serveur MCP intégré permet à l'Assist de Home Assistant de répondre aux questions sur votre plan, avec le modèle de langage que vous utilisez déjà.

## Bêta : on a besoin de vous

WattSlot sert tous les jours dans la maison de son auteur et cherche maintenant des testeurs. Vos retours décident de la suite.

- **[Donner mon avis](https://github.com/jmcruvellier/wattslot/issues/new?template=beta_feedback.yml)** : ce qui marche, ce qui gêne, ce que vous n'avez pas compris, en français ou en anglais. Le même lien est dans l'application, en bas des **Réglages**.
- **Limites connues** :
  - WattSlot **recommande seulement** : il ne lance jamais un appareil et ne pilote jamais votre batterie. C'est vous qui lancez l'appareil, ou qui écrivez l'automatisation.
  - Il part du **tableau Énergie** de Home Assistant : celui-ci doit être configuré.
  - La bêta est surtout testée avec des contrats français (heures creuses, Tempo). Les autres tarifs fonctionnent, et vos retours sur eux sont particulièrement bienvenus.
- **Relecteurs natifs recherchés** : les traductions allemande, néerlandaise, espagnole et italienne attendent un relecteur dont c'est la langue. Voir [CONTRIBUTING.md](CONTRIBUTING.md) ou ouvrir un [ticket de traduction](https://github.com/jmcruvellier/wattslot/issues/new/choose).

## Vie privée

- WattSlot tourne **entièrement chez vous** : pas de compte, pas de service en ligne, pas de télémétrie.
- Votre maison, vos réglages, vos mesures et vos plans restent dans son dossier de données, compris dans les sauvegardes de Home Assistant.
- Rien sur vous ne sort de chez vous. En dehors de Home Assistant, WattSlot n'appelle qu'**Open-Meteo** pour la prévision solaire, quand Home Assistant n'en donne pas (position arrondie à 1 km environ), et GitHub pour connaître les nouvelles versions. Le détail dans [Vie privée](docs/fr/privacy.md).

## Prérequis

- **Home Assistant OS ou Supervised** pour installer WattSlot comme application, sur `amd64` ou `aarch64` (Raspberry Pi 5 avec un SSD, mini PC…). Voir les [conseils de matériel](docs/fr/installation.md).
- Ou **Docker** à côté de n'importe quelle installation de Home Assistant (mode autonome, plus bas).
- Le **tableau Énergie** de Home Assistant configuré.

## Installation

### Comme application de Home Assistant (recommandé)

[![Ajouter le dépôt WattSlot à mon Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjmcruvellier%2Fwattslot%23addon)

1. Cliquez sur le bouton ci-dessus, ou ajoutez `https://github.com/jmcruvellier/wattslot#addon` dans **Paramètres → Applications → Boutique → ⋮ → Dépôts**.
2. Installez **WattSlot**, cochez **Afficher dans la barre latérale**, puis **Démarrer**.
3. Ouvrez WattSlot depuis la barre latérale et suivez les premiers pas : ils vérifient la connexion, les appareils trouvés dans votre tableau Énergie, votre contrat, puis calculent un premier plan.

Les mises à jour arrivent comme pour toute application, avec la sauvegarde automatique de Home Assistant.

### En mode autonome (Docker)

```bash
docker run -d --name wattslot --restart unless-stopped \
  -p 8100:8100 -v wattslot-data:/data \
  -e HA_URL=http://homeassistant.local:8123 \
  ghcr.io/jmcruvellier/wattslot:latest
```

Ouvrez `http://<hôte>:8100` et connectez-vous avec Home Assistant depuis la page de connexion (ou passez un jeton d'accès longue durée dans `HA_TOKEN`). Gardez le port 8100 sur votre réseau local.

## Documentation

- [Guide d'utilisation](docs/fr/) (installation, premiers pas, écrans, tarifs, batterie, assistant, FAQ)
- [Journal des versions](ha-addon/wattslot/CHANGELOG.md)

## Aide et contributions

- **Questions et idées** : les [Discussions](https://github.com/jmcruvellier/wattslot/discussions), en français ou en anglais.
- **Bogues** : [ouvrez un ticket](https://github.com/jmcruvellier/wattslot/issues/new/choose) et joignez le rapport anonymisé de **Réglages → État de l'application → Préparer un rapport**.
- **Contribuer** (code, traductions) : [CONTRIBUTING.md](CONTRIBUTING.md). **Sécurité** : [SECURITY.md](SECURITY.md).

## Soutenir WattSlot

WattSlot est libre et gratuit, sans publicité ni collecte de données. S'il vous fait faire des économies, vous pouvez soutenir son développement, chaque mois ou une fois :

<p>
  <a href="https://github.com/sponsors/jmcruvellier"><img src="docs/images/support-github-sponsors.svg" alt="Soutenir WattSlot sur GitHub Sponsors" height="40"></a>
  &nbsp;
  <a href="https://ko-fi.com/jmcruvellier"><img src="docs/images/support-ko-fi.svg" alt="Soutenir WattSlot sur Ko-fi" height="40"></a>
</p>

## Licence

[Licence Apache 2.0](LICENSE). WattSlot donne des recommandations et ne pilote pas vos appareils ; il est fourni sans garantie (voir la licence).
