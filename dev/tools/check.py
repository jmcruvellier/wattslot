"""Contrôle de bout en bout de l'environnement de développement (lancé aussi par la CI).

    docker compose -f dev/docker-compose.yml --profile check run --rm check

Après l'amorçage et une simulation, vérifie que :
- le HA de test porte les entités simulées et la liste de tâches ;
- l'application est connectée à ce HA et lit son tableau Énergie.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from tools import home
from tools.ha_api import read_token, request

APP_URL = os.environ.get("APP_URL", "http://localhost:8100").rstrip("/")


def app_get(path: str) -> Any:
    with urllib.request.urlopen(APP_URL + path, timeout=10) as response:
        return json.loads(response.read())


def app_put(path: str, payload: Any) -> Any:
    req = urllib.request.Request(
        APP_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def check_ingestion(proposal: dict[str, Any], token: str) -> None:
    """Enregistre la maison simulée, écrit une valeur dans HA, la retrouve dans l'ingestion."""
    model = {
        "devices": [
            {
                "key": d["key"],
                "kind": d["kind"],
                "name": d["name"],
                "capacity_kwh": d["capacity_kwh"],
                "sensors": [
                    {k: s[k] for k in ("entity_id", "role", "resets_daily")}
                    for s in d["sensors"]
                    if not s["excluded"]
                ],
            }
            for d in proposal["devices"]
        ]
    }
    saved = app_put("/api/home", model)
    check(len(saved["devices"]) == len(model["devices"]), "maison simulée enregistrée")

    sensor = home.SOLAR_POWER
    payload = {"state": "4321", "attributes": sensor.attributes()}
    request("POST", f"/api/states/{sensor.entity_id}", token=token, payload=payload)
    deadline = time.monotonic() + 60
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = app_get("/api/ingestion")
        entity = next((e for e in status["entities"] if e["entity_id"] == sensor.entity_id), None)
        if entity and entity["last_value"] == 4321 and status["written"] > 0:
            break
        time.sleep(1)
    else:
        raise AssertionError(f"valeur non ingérée : {status}")
    check(status["running"], f"ingestion active, {len(status['entities'])} entités suivies")
    check(bool(status["days"]), f"relevés écrits dans le magasin du jour {status['days']}")


def check_aggregation() -> None:
    """Attend le premier calcul des agrégats et la reprise des statistiques du HA de test.

    Valide surtout la commande ``recorder/statistics_during_period`` face à un vrai HA : une
    erreur y laisserait les entités en attente, avec ``last_error``.
    """
    deadline = time.monotonic() + 180  # l'agrégation tourne toutes les minutes
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = app_get("/api/aggregation")
        history = status["history"]
        if status["last_run_at"] and history["imported"] and not history["pending"]:
            break
        time.sleep(5)
    else:
        raise AssertionError(f"agrégation ou reprise de l'historique incomplète : {status}")
    check(status["last_error"] is None, "agrégation sans erreur")
    check(
        status["history"]["imported"] > 0,
        f"historique de HA repris pour {status['history']['imported']} entités",
    )


def check_problems() -> None:
    """Diagnostic pour tous (lot 4.8) : sur une installation saine, aucun problème de connexion,
    de capteur, de composant ni de configuration. La prévision (selon le HA de test) et les
    statistiques (simulateur) peuvent manquer sans que l'installation soit en panne."""
    tolerated = {"no_forecast", "no_statistics", "sensor_silent"}
    codes = [p["code"] for p in app_get("/api/diagnostic/problems")]
    unexpected = [code for code in codes if code not in tolerated]
    check(unexpected == [], f"aucun problème inattendu au diagnostic {unexpected or ''}")
    report = app_get("/api/diagnostic/report")
    check(report["format"] == "wattslot/report", "rapport anonymisé disponible")


def wait_for_connection(timeout_s: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    health: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            health = app_get("/api/health")
            if health["connections"]["home_assistant"]["state"] == "connected":
                return health
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(2)
    raise AssertionError(f"application non connectée à HA : {health}")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"OK  {message}")


def main() -> int:
    token = read_token()

    solar = request("GET", f"/api/states/{home.SOLAR_POWER.entity_id}", token=token)
    check(float(solar["state"]) >= 0, f"{home.SOLAR_POWER.entity_id} = {solar['state']} W")
    soc = request("GET", f"/api/states/{home.BATTERY_SOC.entity_id}", token=token)
    check(0 <= float(soc["state"]) <= 100, f"{home.BATTERY_SOC.entity_id} = {soc['state']} %")
    states = request("GET", "/api/states", token=token)
    todo = [s["entity_id"] for s in states if s["entity_id"].startswith("todo.")]
    check(home.TODO_ENTITY_ID in todo, f"liste de tâches {home.TODO_ENTITY_ID} présente")

    health = wait_for_connection()
    version = health["connections"]["home_assistant"]["version"]
    check(health["mode"] == "standalone", f"application en mode autonome, HA {version}")

    sources = app_get("/api/energy/sources")
    check(sources["configured"], "tableau Énergie lu par l'application")
    check(
        [s["energy"] for s in sources["solar"]] == [home.SOLAR_ENERGY.entity_id],
        "production solaire détectée",
    )
    check(
        sources["grid"]["imports"] == [home.GRID_IMPORT.entity_id]
        and sources["grid"]["exports"] == [home.GRID_EXPORT.entity_id],
        "compteurs réseau détectés",
    )
    check(
        [b["state_of_charge"] for b in sources["batteries"]] == [home.BATTERY_SOC.entity_id],
        "batterie détectée",
    )
    check(
        sorted(d["energy"] for d in sources["devices"])
        == sorted(device.energy.entity_id for device in home.DEVICES.values()),
        f"{len(sources['devices'])} équipements détectés",
    )

    # refresh : l'application a lu HA avant que le simulateur n'écrive les états.
    proposal = app_get("/api/home/proposals?refresh=true")
    kinds = sorted(d["kind"] for d in proposal["devices"])
    expected = sorted(
        [
            "SolarInstallation",
            "GridConnection",
            "Battery",
            "WaterHeater",
            "WashingMachine",
            "Dryer",
            "Dishwasher",
        ]
    )
    check(kinds == expected, f"rôles proposés : {', '.join(kinds)}")
    issues = [i["code"] for d in proposal["devices"] for i in d["issues"]]
    check(issues == [], f"aucune anomalie sur la maison simulée {issues or ''}")

    check_ingestion(proposal, token)
    check_aggregation()
    check_problems()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as error:
        print(f"ÉCHEC  {error}", file=sys.stderr)
        sys.exit(1)
