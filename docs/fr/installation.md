# Installation

*[English version](../installation.md) · [Guide d'utilisation](README.md)*

WattSlot s'installe de deux façons ; c'est la même application dans les deux cas.

| | Application de Home Assistant (module complémentaire) | Mode autonome (Docker) |
|---|---|---|
| Pour | Home Assistant OS ou Supervised | N'importe quel Home Assistant (Container, Core…) |
| Connexion à Home Assistant | Automatique | Connexion avec votre compte Home Assistant, ou jeton d'accès longue durée |
| S'ouvre depuis | La barre latérale de Home Assistant | `http://<hôte>:8100` |
| Mises à jour | Depuis Home Assistant, avec sa sauvegarde automatique | `docker compose pull` |

**Matériel** : `amd64` ou `aarch64`. WattSlot garde un historique détaillé, écrit en continu : prenez un **SSD, pas une carte SD** (USB 3 ou NVMe sur un Raspberry Pi), 128 Go conseillés (64 Go au minimum) pour Home Assistant OS avec WattSlot. Sur Raspberry Pi, un **Pi 5 avec 8 Go** est conseillé : la première reprise de l'historique demande jusqu'à 1 Go de mémoire environ à l'application. Un mini PC ou une machine virtuelle avec un SSD n'a pas de contrainte particulière ; dans une machine virtuelle, choisissez le type de CPU **host** (ou **x86-64-v2-AES** sous Proxmox), voir [Dépannage](troubleshooting.md).

**Avant de commencer** : configurez le **tableau Énergie** de Home Assistant (Paramètres › Tableaux de bord › Énergie), avec au moins votre compteur, et votre production solaire si vous avez des panneaux. WattSlot part de lui.

## Comme application de Home Assistant (conseillé)

1. Ajoutez le dépôt à votre Home Assistant :

   [![Ajouter le dépôt WattSlot à mon Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjmcruvellier%2Fwattslot%23addon)

   Ou à la main : **Paramètres › Applications › Boutique des applications › ⋮ › Dépôts**, ajoutez `https://github.com/jmcruvellier/wattslot#addon`, puis **Fermer**.
2. Actualisez la boutique (**⋮ › Rechercher des mises à jour**), ouvrez **WattSlot**, cliquez sur **Installer**.
3. Cochez **Afficher dans la barre latérale**, puis **Démarrer**.
4. Ouvrez **WattSlot** depuis la barre latérale et suivez les [Premiers pas](getting-started.md).

### Options

Dans **Paramètres › Applications › WattSlot › Configuration** :

| Option | Par défaut | Rôle |
|---|---|---|
| Niveau des journaux | info | `debug` quand on vous le demande pour un signalement |
| Relevés bruts conservés | 3 jours | Chaque mesure (1 à 30 jours) |
| Quarts d'heure conservés | 35 jours | Moyennes par quart d'heure (31 à 3 660 jours) ; les moyennes horaires sont gardées sans limite |

### Mises à jour et sauvegardes

- **Mises à jour** : Home Assistant propose **Mettre à jour** quand une nouvelle version est publiée, et fait d'abord une sauvegarde si vous laissez l'option cochée. **Réglages › État de l'application** indique aussi quand une nouvelle version existe.
- **Sauvegardes** : les sauvegardes de Home Assistant incluent WattSlot. L'application fige une copie cohérente de ses données pendant la sauvegarde, sans s'arrêter. Les relevés bruts en sont exclus (ils se reconstruisent depuis l'historique de Home Assistant après une restauration).

### Désinstaller

**Paramètres › Applications › WattSlot › Désinstaller** supprime l'application **et ses données**. Faites d'abord une sauvegarde si vous pensez revenir, ou exportez votre maison (**Ma maison › Avancé › Sauvegarder ou partager**).

## En mode autonome (Docker)

```bash
docker run -d --name wattslot --restart unless-stopped \
  -p 8100:8100 -v wattslot-data:/data \
  -e HA_URL=http://homeassistant.local:8123 \
  ghcr.io/jmcruvellier/wattslot:latest
```

Ou avec Docker Compose :

```yaml
services:
  wattslot:
    image: ghcr.io/jmcruvellier/wattslot:latest
    restart: unless-stopped
    ports: ["8100:8100"]
    volumes: ["wattslot-data:/data"]
    environment:
      HA_URL: http://homeassistant.local:8123
volumes:
  wattslot-data:
```

Ouvrez ensuite `http://<hôte>:8100` :

- **Réglages › Connexion à Home Assistant** (conseillé) : saisissez l'adresse de votre Home Assistant, cliquez sur **Se connecter avec Home Assistant**, confirmez sur la page de votre Home Assistant ; vous revenez connecté.
- Ou créez un **jeton d'accès longue durée** dans Home Assistant (Profil › Sécurité) et passez-le dans `HA_TOKEN`.

**Sécurité** : en mode autonome, WattSlot n'a pas de connexion propre. Gardez le port 8100 sur votre réseau local ; ne l'ouvrez jamais sur Internet. Pour le protéger des pages web ouvertes dans la maison :

- WattSlot ne répond qu'ouvert par une adresse IP, un nom sans point (`http://nas:8100`) ou un nom local (`.local`, `.lan`, `.home.arpa`, `.internal`). Derrière un proxy inverse ou avec un autre nom de domaine, ajoutez-le à `WATTSLOT_ALLOWED_HOSTS`.
- Une modification envoyée par un autre site est refusée.
- La discussion avec les agents de Home Assistant depuis l'écran **Assistant** est désactivée : Assist peut commander vos appareils, n'importe qui sur votre réseau pourrait donc s'en servir. Définissez `WATTSLOT_HOME_ASSISTANT_CHAT=true` pour l'activer. Les modèles d'Open WebUI restent disponibles : ils n'utilisent que les outils de WattSlot.

**Mettre à jour** : `docker compose pull && docker compose up -d` (ou téléchargez l'image et recréez le conteneur). Fixez une version (`ghcr.io/jmcruvellier/wattslot:0.9.0`) si vous préférez mettre à jour à la main.

**Vérifier l'image** : les versions publiées après la 0.9.5 sont signées avec [Cosign](https://docs.sigstore.dev/), sans clé : la signature prouve que l'image a été publiée par le workflow de publication de WattSlot sur GitHub. Pour vérifier une version (ici `X.Y.Z`) :

```bash
cosign verify ghcr.io/jmcruvellier/wattslot:X.Y.Z \
  --certificate-identity "https://github.com/jmcruvellier/wattslot/.github/workflows/release.yml@refs/tags/vX.Y.Z" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Home Assistant ne vérifie pas encore les signatures ; c'est pour qui veut vérifier à la main.

**Utilisateur de l'application** : en mode autonome, WattSlot tourne sous l'utilisateur `wattslot` (utilisateur et groupe `1000`), pas en root, par défense en profondeur. À son premier démarrage après la mise à jour, il lui donne `/data`, une fois (quelques secondes) ; avec un volume nommé, il n'y a rien à faire.

- Avec un dossier de l'hôte au lieu d'un volume nommé, son propriétaire sur l'hôte devient `1000`. Définissez `WATTSLOT_UID` et `WATTSLOT_GID` pour utiliser plutôt votre propre utilisateur.
- Un fichier monté depuis l'hôte, comme celui de `HA_TOKEN_FILE`, doit être lisible par cet utilisateur.
- `--user` (ou `user:` sous le service dans Docker Compose) fonctionne toujours : WattSlot tourne alors sous cet utilisateur et ne touche pas à `/data`, qui doit donc déjà lui appartenir :

  ```bash
  docker run --rm -v wattslot-data:/data --entrypoint chown \
    ghcr.io/jmcruvellier/wattslot:latest -R <utilisateur>:<groupe> /data
  ```

- `WATTSLOT_RUN_AS_ROOT=true` le garde en root.

L'application de Home Assistant reste en root, sous son profil AppArmor.

| Variable | Rôle |
|---|---|
| `HA_URL` | L'adresse de votre Home Assistant, telle que vous l'ouvrez dans un navigateur |
| `HA_TOKEN` | Jeton d'accès longue durée (facultatif avec la page de connexion) |
| `HA_TOKEN_FILE` | Ou le chemin d'un fichier qui contient le jeton (secret Docker) |
| `WATTSLOT_DATA_DIR` | Dossier des données, `/data` dans l'image |
| `TZ` | Fuseau des journaux ; le plan suit celui de Home Assistant |
| `WATTSLOT_ALLOWED_HOSTS` | Noms d'hôte admis en plus des adresses locales, séparés par des virgules (proxy inverse, nom de domaine local comme `wattslot.example.net`) ; voir *Sécurité* plus haut |
| `WATTSLOT_HOME_ASSISTANT_CHAT` | `true` pour discuter avec les agents de Home Assistant depuis l'écran **Assistant** ; désactivé par défaut en mode autonome |
