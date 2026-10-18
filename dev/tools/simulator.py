"""Rejoue une journée dans le HA de test, en écrivant les états des entités simulées.

    python -m tools.simulator                          # temps réel, à partir de l'heure de HA
    python -m tools.simulator --speed 60 --start 08:00 # une minute simulée par seconde
    python -m tools.simulator --day donnees/journee-couverte.json --start 10:00 --end 12:00

Les états sont horodatés par HA à leur réception : en accéléré, une journée simulée occupe
moins de temps dans l'historique de HA. La batterie est simulée depuis minuit pour que son
état de charge soit cohérent à l'heure de départ. Les compteurs reprennent la valeur qu'ils ont
dans HA, pour rester croissants d'une exécution à l'autre.
"""

import argparse
import http.client
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from tools import home
from tools.ha_api import ha_url, read_token, request
from tools.simulation import DAY_S, Day, House

DEFAULT_DAY = Path(__file__).resolve().parent.parent / "donnees" / "journee-ensoleillee.json"


def parse_time(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60


class StateWriter:
    """Écrit les états par l'API REST, sur une connexion HTTP gardée ouverte."""

    def __init__(self, token: str) -> None:
        parts = urllib.parse.urlsplit(ha_url())
        connection_class = (
            http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        )
        self._connection = connection_class(parts.netloc, timeout=30)
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def write(self, sensor: home.Sensor, value: float, digits: int) -> None:
        body = json.dumps({"state": f"{value:.{digits}f}", "attributes": sensor.attributes()})
        self._connection.request("POST", f"/api/states/{sensor.entity_id}", body, self._headers)
        response = self._connection.getresponse()
        response.read()
        if response.status >= 400:
            raise RuntimeError(f"{sensor.entity_id} : HTTP {response.status}")


def current_value(sensor: home.Sensor, token: str) -> float:
    try:
        state = request("GET", f"/api/states/{sensor.entity_id}", token=token)["state"]
        return float(state)
    except Exception:  # noqa: BLE001 — entité absente ou non numérique : on part de zéro
        return 0.0


def ha_seconds_since_midnight(token: str) -> int:
    """Heure locale de HA (évite de dépendre du fuseau du conteneur)."""
    template = "{{ now().hour * 3600 + now().minute * 60 + now().second }}"
    req = urllib.request.Request(
        ha_url() + "/api/template",
        data=json.dumps({"template": template}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return int(response.read().decode().strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--day", type=Path, default=DEFAULT_DAY, help="fichier de journée JSON")
    parser.add_argument("--speed", type=float, default=1.0, help="secondes simulées par seconde")
    parser.add_argument("--step", type=int, default=60, help="pas de simulation, en secondes")
    parser.add_argument("--start", help="heure de départ HH:MM (défaut : heure de HA)")
    parser.add_argument("--end", default="24:00", help="heure de fin HH:MM (défaut : minuit)")
    args = parser.parse_args()

    token = read_token()
    day = Day.load(args.day)
    house = House(day)
    start_s = parse_time(args.start) if args.start else ha_seconds_since_midnight(token)
    end_s = min(parse_time(args.end), DAY_S)

    # Batterie amenée à l'heure de départ ; les compteurs repartent de leur valeur dans HA.
    t = 0
    while t + args.step <= start_s:
        house.step(t, args.step)
        t += args.step
    counters = {
        home.SOLAR_ENERGY: lambda: house.solar_energy_kwh,
        home.GRID_IMPORT: lambda: house.grid_import_kwh,
        home.GRID_EXPORT: lambda: house.grid_export_kwh,
        home.BATTERY_CHARGE: lambda: house.battery_charge_kwh,
        home.BATTERY_DISCHARGE: lambda: house.battery_discharge_kwh,
        **{
            device.energy: (lambda key=key: house.device_energy_kwh.get(key, 0.0))
            for key, device in home.DEVICES.items()
        },
    }
    offsets = {sensor: current_value(sensor, token) - read() for sensor, read in counters.items()}

    writer = StateWriter(token)
    print(f"Journée « {day.name} » de {args.start or 'maintenant'} à {args.end}, x{args.speed}")
    started = time.monotonic()
    simulated = 0.0
    while t < end_s:
        readings = house.step(t, args.step)
        writer.write(home.SOLAR_POWER, readings["solar_w"], 0)
        writer.write(home.HOME_POWER, readings["home_w"], 0)
        writer.write(home.GRID_POWER, readings["grid_w"], 0)
        for key, device in home.DEVICES.items():
            writer.write(device.power, readings.get(f"{key}_w", 0.0), 0)
        if day.battery:
            writer.write(home.BATTERY_POWER, readings["battery_w"], 0)
            writer.write(home.BATTERY_SOC, house.soc_pct or 0.0, 1)
        for sensor, read in counters.items():
            if sensor in (home.BATTERY_CHARGE, home.BATTERY_DISCHARGE) and not day.battery:
                continue
            writer.write(sensor, offsets[sensor] + read(), 3)
        t += args.step
        simulated += args.step
        delay = started + simulated / args.speed - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    print("Journée terminée.")


if __name__ == "__main__":
    main()
