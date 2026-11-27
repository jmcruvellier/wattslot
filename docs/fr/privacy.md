# Confidentialité

*[English version](../privacy.md) · [Guide d'utilisation](README.md)*

WattSlot tourne entièrement chez vous. Il n'a ni compte, ni service en ligne, ni télémétrie.

## Ce qui reste chez vous

Tout : la description de votre maison, vos réglages, vos mesures et vos plans sont rangés dans le dossier de données de WattSlot (le dossier de l'application dans Home Assistant, ou le volume Docker en mode autonome), et inclus dans les sauvegardes de Home Assistant.

## Les seules connexions sortantes

| Qui | Vers | Quand | Ce qui est envoyé |
|---|---|---|---|
| WattSlot (le serveur) | Home Assistant | Toujours | Il lit vos capteurs, le tableau Énergie et les statistiques ; il envoie les notifications |
| WattSlot (le serveur) | `api.open-meteo.com` | Seulement si vous avez décrit vos panneaux et que Home Assistant ne donne pas de prévision | Votre position arrondie à environ 1 km (0,01°), au plus une fois par heure et par champ de panneaux |
| Votre navigateur | `api.github.com` | Quand l'application est ouverte, au plus une fois par heure | Rien sur vous : il lit la dernière version de WattSlot pour vous signaler les mises à jour |
| Home Assistant | votre modèle de langage | Seulement si vous avez branché l'[assistant vocal](assistant.md) | Vos questions et les réponses que WattSlot donne à l'Assist ; avec un modèle local (Ollama), cela reste chez vous |

## Ce qui ne sort que si vous le décidez

- **Exports** (**Ma maison › Sauvegarder ou partager**) : votre maison et ses réglages dans un fichier. Votre connexion à Home Assistant n'y figure jamais.
- **Rapports** (**Réglages › État de l'application › Préparer un rapport**) : l'état de l'application, sans nom d'équipement, ni identifiant de capteur, ni position, à joindre à un signalement. Vous voyez tout ce qu'il contient avant de le télécharger.

## Sécurité

WattSlot **recommande** seulement : il ne lance jamais un appareil et ne pilote jamais votre batterie. Comme application de Home Assistant, il n'est joignable que par Home Assistant ; en mode autonome, gardez-le sur votre réseau local.

Comme application de Home Assistant, WattSlot tourne aussi sous son propre profil AppArmor : il ne peut lire et écrire que son dossier et les fichiers dont il a besoin, et ne peut lancer aucun autre programme que le sien. Il n'a besoin d'aucun accès à l'hôte, à la configuration réseau ni aux autres applications.

Il a en revanche besoin de l'API de Home Assistant, que Home Assistant n'accorde qu'en bloc, avec des droits d'administrateur. WattSlot s'en sert pour lire (états et leurs changements, réglages du tableau Énergie et prévision solaire, historique et statistiques, registres des entités et des appareils, listes de tâches, agents de conversation) et pour agir de deux façons seulement : envoyer les notifications que vous avez réglées, et transmettre vos questions à l'agent de conversation que vous avez choisi. Si vous l'activez (c'est désactivé par défaut), il écrit aussi ses propres capteurs de prévision, nommés `sensor.wattslot_…` ([Capteurs](sensors.md)). Il ne modifie jamais une autre entité, une automatisation ni un réglage de Home Assistant.
