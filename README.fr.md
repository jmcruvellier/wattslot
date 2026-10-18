<p align="center"><img src="ha-addon/wattslot/logo.png" alt="WattSlot" width="250"></p>

# WattSlot

*[English version](README.md)*

**WattSlot trouve le bon créneau pour lancer vos appareils**, pour consommer votre propre électricité solaire ou les heures les moins chères de votre contrat. Il lit votre maison dans Home Assistant, planifie la journée et la semaine, et vous dit quoi lancer et quand : il recommande, vous décidez.

Il fonctionne avec ou sans panneaux solaires ni batterie : un contrat en heures creuses, à jours de couleur (comme Tempo d'EDF) ou à prix dynamiques suffit pour faire des économies.

> **État : bêta.** WattSlot sert tous les jours dans la maison de son auteur et cherche maintenant des testeurs. Vos retours sont les bienvenus.

## Fonctions

- **Lit votre maison dans Home Assistant** : le tableau Énergie donne la production solaire, le réseau, la batterie et les appareils suivis ; l'historique vient des statistiques de Home Assistant. Rien à saisir pour commencer.
- **Plan du jour et horizon de sept jours** : quand lancer chaque appareil, quand charger ou décharger la batterie, d'après la prévision solaire et vos prix (prix unique, heures creuses, jours de couleur, prix dynamiques lus dans une entité).
- **Votre maison, vos règles** : comportement des appareils, plages horaires, récurrences, réglages de la batterie, et ce qu'il faut optimiser (coût, autoconsommation, achat au réseau, CO₂). Modèles prêts à l'emploi, sauvegarde et partage des réglages.
- **Une interface pour tous les jours** : Aujourd'hui, Planning (agenda et courbes détaillées), Ma maison en phrases, Assistant, Réglages. Pensée d'abord pour le téléphone, cinq thèmes avec clair et sombre automatiques, six langues (français, anglais, allemand, néerlandais, espagnol, italien).
- **Demandes et rappels** : demandez un appareil depuis l'application ou depuis l'Assist de Home Assistant, soyez prévenu au bon moment.
- **Assistant (facultatif)** : un serveur MCP intégré permet à l'Assist de Home Assistant de répondre aux questions sur votre plan, avec le modèle de langage que vous utilisez déjà.
- **Diagnostic en clair**, avec un rapport anonymisé à joindre à un signalement.

## Prérequis

- **Home Assistant OS ou Supervised** pour installer WattSlot comme application (module complémentaire), sur `amd64` ou `aarch64` (Raspberry Pi 4 ou 5 avec un SSD, mini PC…).
- Ou **Docker** à côté de n'importe quelle installation de Home Assistant (mode autonome, voir plus bas).
- Le **tableau Énergie** de Home Assistant configuré : WattSlot part de lui.

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

- [Guide d'utilisation](docs/) (installation, premiers pas, écrans, tarifs, batterie, assistant, FAQ)
- [Journal des versions](ha-addon/wattslot/CHANGELOG.md)

## Aide et contributions

- **Questions et idées** : posez-les dans les [Discussions](https://github.com/jmcruvellier/wattslot/discussions), en français ou en anglais.
- **Bogues et idées** : [ouvrez un ticket](https://github.com/jmcruvellier/wattslot/issues/new/choose), en français ou en anglais. Pour un bogue, joignez le rapport anonymisé de **Réglages → État de l'application → Préparer un rapport**.
- **Contribuer** (code, traductions) : voir [CONTRIBUTING.md](CONTRIBUTING.md).
- **Sécurité** : voir [SECURITY.md](SECURITY.md).

Si WattSlot vous fait faire des économies, vous pouvez soutenir son développement sur [GitHub Sponsors](https://github.com/sponsors/jmcruvellier) (chaque mois ou une fois) ou [Ko-fi](https://ko-fi.com/jmcruvellier) (une fois), liens aussi donnés par le bouton **Sponsor** de cette page et dans **Réglages → État de l'application** de l'application.

## Licence

[Licence Apache 2.0](LICENSE). WattSlot donne des recommandations et ne pilote pas vos appareils ; il est fourni sans garantie (voir la licence).
