#!/bin/sh
# Démarrage de l'image : en mode autonome, l'application tourne sous l'utilisateur « wattslot »
# (uid 1000) plutôt qu'en root, par défense en profondeur (#150).
#
# - Extension HA (le Supervisor fournit SUPERVISOR_TOKEN) : inchangée, en root. Le Supervisor
#   monte /data et lance backup_pre / backup_post dans le conteneur, en root ; profil AppArmor.
# - Conteneur déjà lancé sous un autre utilisateur (--user, user: dans Compose) : respecté.
# - WATTSLOT_RUN_AS_ROOT=true : en root, si un montage de l'hôte ne s'y prête pas.
# - Sinon : /data donné à WATTSLOT_UID:WATTSLOT_GID (1000:1000 par défaut) s'il ne lui
#   appartient pas encore (une fois, après la mise à jour), puis l'application est lancée sous
#   cet utilisateur. « exec » jusqu'au bout : uvicorn reste le processus 1 et reçoit les signaux
#   d'arrêt de Docker.
set -eu

# Extension d'abord, avec les seules commandes internes du shell : son profil AppArmor
# (ha-addon/wattslot/apparmor.txt) n'autorise ni id, ni find, ni chown, ni setpriv.
if [ -n "${SUPERVISOR_TOKEN:-}" ] || [ "${WATTSLOT_RUN_AS_ROOT:-}" = true ]; then
    exec "$@"
fi
if [ "$(id -u)" != 0 ]; then
    exec "$@"
fi

uid="${WATTSLOT_UID:-1000}"
gid="${WATTSLOT_GID:-1000}"
case "$uid:$gid" in
    *[!0-9:]* | :* | *:)
        echo "WATTSLOT_UID and WATTSLOT_GID must be numbers (got $uid:$gid)" >&2
        exit 1
        ;;
esac
if [ "$uid" = 0 ]; then
    exec "$@"
fi

data="${WATTSLOT_DATA_DIR:-/data}"
mkdir -p "$data"
# Seulement s'il reste un fichier d'un autre propriétaire : le parcours complet ne coûte qu'au
# premier démarrage (volume créé par root, ou par une version qui tournait en root).
if [ -n "$(find "$data" \( ! -user "$uid" -o ! -group "$gid" \) -print -quit)" ]; then
    echo "WattSlot: giving $data to user $uid:$gid (once, after an update)"
    chown -R "$uid:$gid" "$data"
fi

exec setpriv --reuid="$uid" --regid="$gid" --clear-groups -- "$@"
