"""Frise des vues (lot 5.1, PR 2) : barres prévues identiques à la v1 sur les 13 états, et bilan
des équipements (repris du JavaScript de la page de la v1) cas par cas."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.test_views_day import PARIS, V1_CONTEXT, state_of
from tests.v1_oracle import STATES, v1
from wattslot.views.display import Context
from wattslot.views.timeline import build_timeline, planned_devices, statuses

IDS = [p.stem for p in STATES]
ECO_KW = v1("noeud_calcul.PUISSANCE_ECO_KW")
SILENCE_KW = v1("noeud_calcul.PUISSANCE_SILENCE_KW")


@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_planned_bars_are_those_of_the_v1(path: Path) -> None:
    state = state_of(path)
    planning = state["planning"]
    timeline = build_timeline(state, None, 12.0, 10.0, 8.0, V1_CONTEXT)
    rows = {row.device: row for row in timeline.rows}

    battery = next((i for i in planning if i["equipement"] == "Batterie"), None)
    if battery is not None and battery.get("mouvements"):
        blocks = v1("dashboard._grouper_mouvements_batterie", battery["mouvements"])
        assert [
            (b.start_hour, b.end_hour, b.energy_kwh, b.action) for b in rows["Batterie"].planned
        ] == [
            (
                b["debut"],
                b["fin"],
                round(b["energie_kwh"], 3),
                "charge" if b["action"] == "charge" else "discharge",
            )
            for b in blocks
        ]
    for item in planning:
        if "heure_debut" in item and item["equipement"] != "Batterie":
            start, end = v1("recalage_cycles.bornes_minutes", item)
            bar = rows[item["equipement"]].planned[0]
            assert (bar.start_hour, bar.end_hour) == (start / 60, end / 60)
        if "segments" in item:
            expected = [
                round(
                    (s["heure_fin"] - s["heure_debut"])
                    * (ECO_KW if s["mode"] == "eco" else SILENCE_KW),
                    3,
                )
                for s in item["segments"]
                if s["mode"] != "off"
            ]
            found = rows.get(item["equipement"])
            assert ([b.energy_kwh for b in found.planned] if found else []) == expected
    assert planned_devices(planning, V1_CONTEXT) == v1("dashboard._equipements_prevus", planning)


def test_an_empty_timeline_says_why() -> None:
    state = {"planning": [{"equipement": "Batterie", "mouvements": []}]}
    assert build_timeline(state, None, 12.0, 2.0, 5.0, V1_CONTEXT).empty == "no_surplus"
    assert build_timeline(state, None, 12.0, 6.0, 5.0, V1_CONTEXT).empty == "nothing"
    assert "tl-vide-etat" in v1(
        "dashboard._construire_lignes_gantt", state["planning"], False, 2.0, 5.0
    )


def iso(hour: int, minute: int = 0) -> str:
    return datetime(2026, 10, 17, hour, minute, tzinfo=PARIS).isoformat()


PLANNED = [
    {"nom": "Lave-linge", "debut_min": 600, "fin_min": 690, "energie_kwh": 1.0},
    {"nom": "Lave-vaisselle", "debut_min": 720, "fin_min": 840, "energie_kwh": 1.2},
    {"nom": "Chauffe-eau", "debut_min": 780, "fin_min": 900, "energie_kwh": 2.0},
    {"nom": "Sèche-linge", "debut_min": 1080, "fin_min": 1200, "energie_kwh": 2.5},
    {"nom": "Piscine (filtration)", "debut_min": 660, "fin_min": 900, "energie_kwh": 1.2},
]


def segment(start: str, end: str, kwh: float, running: bool = False) -> dict[str, Any]:
    return {
        "debut_iso": start,
        "fin_iso": end,
        "energie_kwh": kwh,
        **({"en_cours": True} if running else {}),
    }


def test_device_statuses_at_the_last_reading() -> None:
    actual = {
        "equipements_reels_horaire": {
            "Lave-linge": [segment(iso(10, 5), iso(11, 30), 1.3)],  # à l'heure, +30 %
            "Lave-vaisselle": [segment(iso(12, 50), iso(14, 50), 0.8, running=True)],  # +50 min
            "Piscine (filtration)": [
                segment(iso(11), iso(12), 0.4),
                segment(iso(13), iso(14), 0.4),
            ],
            "Déshumidificateur": [segment(iso(9), iso(10), 0.3)],  # hors planning
        }
    }
    found, unplanned, badge = statuses(
        PLANNED, actual, 15.0, {"Piscine (filtration)"}, Context(zone=PARIS)
    )
    by_device = {s.device: s for s in found}

    washer = by_device["Lave-linge"]
    assert (washer.status, washer.actual_start_min, washer.energy_gap_percent) == (
        "on_time",
        605,
        30,
    )
    dishwasher = by_device["Lave-vaisselle"]
    assert (dishwasher.status, dishwasher.shift_min, dishwasher.running) == ("shifted", 50, True)
    assert dishwasher.energy_gap_percent is None  # en cours : pas d'écart d'énergie
    assert by_device["Chauffe-eau"].status == "no_cycle"  # créneau passé à 15 h, rien mesuré
    assert by_device["Sèche-linge"].status == "planned"  # créneau à venir
    pool = by_device["Piscine (filtration)"]
    assert (pool.status, pool.actual_start_min, pool.actual_kwh) == ("on_time", 660, 0.8)
    assert [(u.device, u.start_min, u.energy_kwh) for u in unplanned] == [
        ("Déshumidificateur", 540, 0.3)
    ]
    assert badge == "shifted"


def test_without_actual_data_nothing_is_judged() -> None:
    found, unplanned, badge = statuses(PLANNED, None, 23.0, set(), Context(zone=PARIS))
    assert {s.status for s in found} == {"planned"} and unplanned == [] and badge is None


def test_rows_show_actual_bars_and_hide_empty_appliances() -> None:
    state = {
        "planning": [
            {
                "equipement": "Batterie",
                "mouvements": [{"heure": 11, "action": "charge", "energie_kwh": 0.5}],
            },
            {"equipement": "Lave-linge", "heure_debut": 10, "heure_fin": 12, "energie_kwh": 1.0},
        ]
    }
    actual = {
        "heure_maj_iso": iso(15),
        "batterie_reelle_segments": [{**segment(iso(11), iso(12, 30), 0.6), "action": "charge"}],
        "equipements_reels_horaire": {"Sèche-linge": [segment(iso(13), iso(14), 1.0)]},
    }
    context = Context(zone=PARIS, appliances=("Lave-linge", "Sèche-linge", "Lave-vaisselle"))
    timeline = build_timeline(state, actual, 15.0, 10.0, 8.0, context)

    assert [row.device for row in timeline.rows] == ["Batterie", "Lave-linge", "Sèche-linge"]
    battery = timeline.rows[0].actual[0]
    assert (battery.start_hour, battery.end_hour, battery.action) == (11.0, 12.5, "charge")
    assert timeline.rows[2].planned == [] and timeline.rows[2].actual[0].energy_kwh == 1.0
