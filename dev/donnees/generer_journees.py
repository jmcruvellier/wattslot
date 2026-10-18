"""Génère les journées rejouées par le simulateur, à partir d'une journée type des tests du
serveur (entrée du calcul de la v1, anonymisée : ``app/backend/tests/fixtures/days/``).

    python dev/donnees/generer_journees.py

Repris de la journée : production solaire et consommation de base heure par heure, énergie et
forme au quart d'heure des cycles mesurés des équipements, capacité et puissances de la batterie.
Seuls des profils d'énergie sont repris, avec des noms d'équipements génériques : aucune donnée
personnelle (décision 2). Les heures de démarrage des cycles sont choisies ici.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "app/backend/tests/fixtures/days/06_today_h13_dishwasher_running.json"
OUTPUT = Path(__file__).resolve().parent

DEVICES = {
    "Chauffe-eau": ("water_heater", "11:00"),
    "Lave-linge": ("washing_machine", "10:00"),
    "Sèche-linge": ("dryer", "11:15"),
    "Lave-vaisselle": ("dishwasher", "13:00"),
}

BATTERY = {"initial_soc_pct": 30.0, "min_soc_pct": 12.0, "efficiency": 0.94}


def hourly(values: dict[str, list[list[float]]]) -> list[float]:
    by_hour = dict(values["__dict__"])
    return [round(by_hour.get(hour, 0.0), 4) for hour in range(24)]


def write(name: str, filename: str, solar: list[float], base: list[float], cycles: list, battery):
    day = {
        "name": name,
        "source": f"Journée type {SOURCE.stem} des tests du serveur (profils d'énergie seulement)",
        "hourly": {"solar_kwh": solar, "base_load_kwh": base},
        "cycles": cycles,
        "battery": battery,
    }
    (OUTPUT / filename).write_text(json.dumps(day, ensure_ascii=False, indent=2) + "\n", "utf-8")


def main() -> None:
    state = json.loads(SOURCE.read_text(encoding="utf-8"))["entree"]
    battery = {
        "capacity_kwh": state["capacite_batterie_kwh"],
        "initial_soc_pct": BATTERY["initial_soc_pct"],
        "min_soc_pct": BATTERY["min_soc_pct"],
        "max_charge_w": state["puissance_charge_max_w"],
        "max_discharge_w": state["puissance_decharge_max_w"],
        "efficiency": BATTERY["efficiency"],
    }
    solar = hourly(state["production_solaire_horaire"])
    base = hourly(state["consommation_baseline_horaire"])
    cycles = [
        {
            "device": key,
            "start": start,
            "energy_kwh": state["profils_cycles"][name]["energie_kwh"],
            "shape_per_quarter": state["profils_cycles"][name]["forme_quart_heure"],
        }
        for name, (key, start) in DEVICES.items()
    ]
    write("Journée ensoleillée", "journee-ensoleillee.json", solar, base, cycles, battery)
    cloudy = [round(value * 0.3, 4) for value in solar]
    write("Journée couverte", "journee-couverte.json", cloudy, base, cycles, battery)
    write(
        "Journée ensoleillée sans batterie", "journee-sans-batterie.json", solar, base, cycles, None
    )


if __name__ == "__main__":
    main()
