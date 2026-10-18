"""Amorçage du HA de test, sans aucune saisie.

1. Onboarding par l'API : compte, configuration de base, analytics refusées.
2. Jeton d'accès longue durée, écrit dans ``HA_TOKEN_FILE`` pour l'application et les outils.
3. Réglages de la maison (fuseau, unités, monnaie), liste de tâches, tableau Énergie.

Rejouable : si le jeton existe déjà et reste valide, seules les étapes 3 sont refaites.
"""

import os
import sys
import urllib.error

from tools import home
from tools.ha_api import WebSocketSession, read_token, request, token_file, wait_until_up

CLIENT_ID = "http://wattslot.dev/"
BATTERY_CAPACITY_KWH = 5.12


def onboard() -> str:
    """Crée le compte ; renvoie un jeton d'accès de courte durée."""
    reply = request(
        "POST",
        "/api/onboarding/users",
        payload={
            "client_id": CLIENT_ID,
            "name": "Developer",
            "username": os.environ.get("DEV_HA_USERNAME", "dev"),
            "password": os.environ.get("DEV_HA_PASSWORD", "dev-password"),
            "language": "en",
        },
    )
    tokens = request(
        "POST",
        "/auth/token",
        form={
            "grant_type": "authorization_code",
            "code": reply["auth_code"],
            "client_id": CLIENT_ID,
        },
    )
    access_token: str = tokens["access_token"]
    request("POST", "/api/onboarding/core_config", token=access_token)
    request("POST", "/api/onboarding/analytics", token=access_token)
    request(
        "POST",
        "/api/onboarding/integration",
        token=access_token,
        payload={"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID},
    )
    return access_token


def valid_saved_token() -> str | None:
    if not token_file().is_file():
        return None
    token = read_token()
    try:
        request("GET", "/api/", token=token)
    except urllib.error.HTTPError:
        return None
    return token


def configure(session: WebSocketSession, token: str) -> None:
    session.command(
        "config/core/update",
        time_zone="Europe/Paris",
        unit_system="metric",
        currency="EUR",
        country="FR",
        language="en",
    )
    entries = request("GET", "/api/config/config_entries/entry?domain=local_todo", token=token)
    if not entries:
        flow = request(
            "POST",
            "/api/config/config_entries/flow",
            token=token,
            payload={"handler": "local_todo"},
        )
        request(
            "POST",
            f"/api/config/config_entries/flow/{flow['flow_id']}",
            token=token,
            payload={"todo_list_name": home.TODO_LIST_NAME},
        )
    session.command("energy/save_prefs", **home.energy_preferences(BATTERY_CAPACITY_KWH))


def main() -> int:
    wait_until_up()
    token = valid_saved_token()
    if token is None:
        steps = request("GET", "/api/onboarding")
        if not any(step["step"] == "user" and not step["done"] for step in steps):
            print(
                "Le HA de test est déjà initialisé mais le jeton est perdu : repartir de zéro avec "
                "« docker compose -f dev/docker-compose.yml down -v ».",
                file=sys.stderr,
            )
            return 1
        access_token = onboard()
        with WebSocketSession(access_token) as session:
            token = session.command(
                "auth/long_lived_access_token", client_name="wattslot-dev", lifespan=3650
            )
        token_file().parent.mkdir(parents=True, exist_ok=True)
        token_file().write_text(token, encoding="utf-8")
        print("Compte et jeton créés.")
    with WebSocketSession(token) as session:
        configure(session, token)
    print("HA de test prêt : réglages, liste de tâches et tableau Énergie en place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
