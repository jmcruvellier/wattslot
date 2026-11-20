"""Frise des vues (lot 5.1, PR 2) : barres prévues identiques à la v1 sur les 13 états, et bilan
des équipements (repris du JavaScript de la page de la v1) cas par cas."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.test_views_day import PARIS, V1_CONTEXT, state_of
from tests.v1_oracle import STATES, v1
from wattslot.views.display import Context
from wattslot.views.timeline import (
    MIN_BATTERY_BAR_KWH,
    build_timeline,
    planned_devices,
    statuses,
)

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
            if b["energie_kwh"] >= MIN_BATTERY_BAR_KWH
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


def test_an_activity_before_a_request_is_not_its_cycle() -> None:
    """20/11/2026 : lessive faite à 3 h, nouvelle lessive demandée à 8 h 21 et prévue à 10 h.
    La frise la disait « lancée à 3 h » : « Prochaine action » ne la proposait pas."""
    planning = [
        {
            "equipement": "Lave-linge",
            "heure_debut": 10,
            "heure_fin": 12,
            "debut_min": 600,
            "fin_min": 720,
            "energie_kwh": 0.4,
            "demande": "app-47",
        }
    ]
    actual = {"equipements_reels_horaire": {"Lave-linge": [segment(iso(3), iso(4, 15), 0.37)]}}
    context = Context(zone=PARIS)

    def status(asked: dict[str, str]) -> str:
        found, _, _ = statuses(
            planned_devices(planning, context, asked), actual, 9.9, set(), context
        )
        return found[0].status

    assert status({"app-47": iso(8, 21)}) == "planned"
    assert status({"app-47": iso(2)}) == "shifted"  # demandée avant : c'est bien son cycle
    assert status({}) == "shifted"  # tâche sans moment de demande : comme avant


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
    context = Context(
        zone=PARIS,
        appliances=("Lave-linge", "Sèche-linge", "Lave-vaisselle"),
        kinds={"Batterie": "Battery", "Lave-linge": "WashingMachine"},
    )
    timeline = build_timeline(state, actual, 15.0, 10.0, 8.0, context)

    assert [row.device for row in timeline.rows] == ["Batterie", "Lave-linge", "Sèche-linge"]
    # Type de l'équipement pour l'icône de sa ligne : aucun pour la batterie ni pour un inconnu.
    assert [row.type for row in timeline.rows] == [None, "WashingMachine", None]
    battery = timeline.rows[0].actual[0]
    assert (battery.start_hour, battery.end_hour, battery.action) == (11.0, 12.5, "charge")
    assert timeline.rows[2].planned == [] and timeline.rows[2].actual[0].energy_kwh == 1.0


def test_a_battery_movement_of_a_few_wh_is_not_shown() -> None:
    """« 0,0 kWh » : quelques Wh au-dessus du plancher, pas un mouvement à montrer."""
    state = {
        "planning": [
            {
                "equipement": "Batterie",
                "mouvements": [
                    {"heure": 11, "action": "charge", "energie_kwh": 0.5},
                    {"heure": 13, "action": "decharge", "energie_kwh": 0.012},
                ],
            }
        ]
    }
    timeline = build_timeline(state, None, 12.0, 10.0, 8.0, V1_CONTEXT)

    assert [(b.start_hour, b.action) for b in timeline.rows[0].planned] == [(11, "charge")]


def test_a_cycle_carried_from_the_day_before_starts_the_timeline() -> None:
    """Débordement après minuit : la fin du chauffe-eau d'hier (0 h-1 h) ouvre la frise, sur la
    ligne de l'appareil s'il est aussi prévu aujourd'hui, sans action à lancer."""
    state = state_of(STATES[0])
    state["suite_veille"] = [
        {"equipement": "Chauffe-eau", "fin_min": 60, "energie_kwh": 0.6, "horaire": {"0": 0.6}},
        {"equipement": "Sèche-linge", "fin_min": 30, "energie_kwh": 0.2, "horaire": {"0": 0.2}},
    ]
    timeline = build_timeline(state, None, 12.0, 10.0, 8.0, V1_CONTEXT)

    rows = {row.device: row for row in timeline.rows}
    first = rows["Sèche-linge"].planned[0]
    assert (first.start_hour, first.end_hour, first.carried) == (0, 0.5, True)
    heater = rows["Chauffe-eau"].planned
    assert heater[0].carried and heater[0].end_hour == 1.0
    assert all(not bar.carried for bar in heater[1:])


def test_several_cycles_of_one_device_share_a_row() -> None:
    """Deux lessives le même jour : une ligne « Lave-linge », une barre par cycle, et chaque
    cycle prévu jugé sur son propre cycle réel."""
    washer = {"equipement": "Lave-linge", "energie_kwh": 1.0, "duree_cycle_min": 90}
    state = {
        "planning": [
            {**washer, "heure_debut": 14, "heure_fin": 16, "debut_min": 840, "fin_min": 930}
            | {"rang": 2},
            {**washer, "heure_debut": 10, "heure_fin": 12, "debut_min": 600, "fin_min": 690},
        ]
    }
    timeline = build_timeline(state, None, 12.0, 10.0, 8.0, Context(zone=PARIS))
    rows = [row for row in timeline.rows if row.device == "Lave-linge"]
    assert len(rows) == 1
    assert [(bar.start_hour, bar.end_hour) for bar in rows[0].planned] == [(10, 11.5), (14, 15.5)]

    # À 13 h, seul le premier cycle a tourné : il n'est pas compté aussi pour le second.
    planned = [
        {"nom": "Lave-linge", "debut_min": 600, "fin_min": 690, "energie_kwh": 1.0},
        {"nom": "Lave-linge", "debut_min": 840, "fin_min": 930, "energie_kwh": 1.0},
    ]
    actual = {"equipements_reels_horaire": {"Lave-linge": [segment(iso(10, 5), iso(11, 30), 1.0)]}}
    found, _, badge = statuses(planned, actual, 13.0, set(), Context(zone=PARIS))
    assert [(s.status, s.actual_start_min) for s in found] == [("on_time", 605), ("planned", None)]
    assert badge == "on_time"


def cycle(device: str, start: int, end: int, rank: int | None = None) -> dict[str, Any]:
    return {
        "equipement": device,
        "heure_debut": start,
        "heure_fin": end,
        "energie_kwh": 1.0,
        **({"rang": rank} if rank else {}),
    }


LAUNDRY = Context(
    zone=PARIS,
    appliances=("Lave-vaisselle", "Sèche-linge", "Lave-linge", "Chauffe-eau"),
    follows={"Sèche-linge": "Lave-linge"},
)


def test_rows_follow_the_first_start_of_the_day_after_the_batteries() -> None:
    """Demande du 20/11/2026 : les batteries d'abord, puis les équipements dans l'ordre de leur
    premier lancement prévu ou réel ; un équipement qui en suit un autre juste après lui, même
    s'il a tourné plus tôt ; la filtration en dernier."""
    state = {
        "planning": [
            {
                "equipement": "Piscine",
                "segments": [{"heure_debut": 1, "heure_fin": 3, "mode": "eco"}],
            },
            cycle("Sèche-linge", 12, 14),
            cycle("Lave-linge", 10, 12),
            cycle("Chauffe-eau", 13, 15),
            {
                "equipement": "Batterie",
                "mouvements": [{"heure": 11, "action": "charge", "energie_kwh": 0.5}],
            },
        ]
    }
    actual = {
        "heure_maj_iso": iso(9),
        "equipements_reels_horaire": {
            # Réveil de veille à 1 h (pas un cycle), vrai cycle à 5 h.
            "Lave-vaisselle": [segment(iso(1), iso(1, 5), 0.01), segment(iso(5), iso(7), 0.9)],
            # Le sèche-linge a tourné à 2 h : il reste sous le lave-linge.
            "Sèche-linge": [segment(iso(2), iso(4), 1.0)],
        },
    }
    timeline = build_timeline(state, actual, 9.0, 10.0, 8.0, LAUNDRY)

    assert [row.device for row in timeline.rows] == [
        "Batterie",
        "Lave-vaisselle",  # 5 h, mesuré
        "Lave-linge",  # 10 h, prévu
        "Sèche-linge",  # juste après celui qu'il suit
        "Chauffe-eau",  # 13 h
        "Piscine",
    ]
    assert [row.follows for row in timeline.rows] == [None, None, None, "Lave-linge", None, None]


def test_a_dependent_row_without_its_parent_row_is_ordered_like_the_others() -> None:
    state = {"planning": [cycle("Chauffe-eau", 13, 15), cycle("Sèche-linge", 9, 11)]}
    timeline = build_timeline(state, None, 8.0, 10.0, 8.0, LAUNDRY)
    assert [(row.device, row.follows) for row in timeline.rows] == [
        ("Sèche-linge", None),
        ("Chauffe-eau", None),
    ]
    assert timeline.links == []


def test_the_dependency_written_in_the_tasks_orders_the_rows_too() -> None:
    """Maison sans réglage « démarre après » : la dépendance des tâches gardées avec le plan."""
    state = {
        "planning": [
            cycle("Sèche-linge", 12, 14),
            cycle("Chauffe-eau", 11, 12),
            cycle("Lave-linge", 10, 12),
        ],
        "taches_placees": [
            {"summary": "Sèche-linge", "uid": "a", "description": {"depend_de": "Lave-linge"}}
        ],
    }
    timeline = build_timeline(state, None, 8.0, 10.0, 8.0, Context(zone=PARIS))
    assert [row.device for row in timeline.rows] == ["Lave-linge", "Sèche-linge", "Chauffe-eau"]
    assert [
        (link.source, link.target, link.from_hour, link.to_hour, link.started)
        for link in timeline.links
    ] == [("Lave-linge", "Sèche-linge", 12.0, 12.0, False)]


def test_links_pair_the_cycles_of_the_day_in_order() -> None:
    """Journée du 20/11/2026 : deux lessives (3 h et 10 h) et deux séchages (10 h et 12 h 45)
    mesurés, puis une troisième lessive et son séchage prévus. Chaque séchage est relié à la
    première lessive finie avant lui et pas encore prise ; plein s'il est lancé, pointillé
    (``started`` faux) s'il est prévu."""
    state = {
        "planning": [
            {**cycle("Sèche-linge", 19, 21, 3), "demande": "app-2"},
            {**cycle("Lave-linge", 17, 19, 3), "demande": "app-1"},
        ],
        # Demandes faites à 16 h : les activités d'avant ne sont pas leurs cycles.
        "taches_placees": [
            {"summary": "Lave-linge", "uid": "app-1", "rang": 3, "demandee_iso": iso(16)},
            {"summary": "Sèche-linge", "uid": "app-2", "rang": 3, "demandee_iso": iso(16)},
        ],
    }
    actual = {
        "heure_maj_iso": iso(16, 30),
        "equipements_reels_horaire": {
            "Lave-linge": [
                segment(iso(3), iso(4, 15), 0.4),
                segment(iso(6, 50), iso(7), 0.01),  # réveil de veille : pas un cycle
                segment(iso(10, 5), iso(11, 45), 0.4),
            ],
            "Sèche-linge": [
                segment(iso(10), iso(12, 30), 1.0),
                segment(iso(12, 45), iso(15, 30), 1.1),
            ],
        },
    }
    timeline = build_timeline(state, actual, 16.5, 10.0, 8.0, LAUNDRY)

    assert [(link.from_hour, link.to_hour, link.started) for link in timeline.links] == [
        (4.25, 10.0, True),
        (11.75, 12.75, True),
        (19.0, 19.0, False),
    ]
    assert {(link.source, link.target) for link in timeline.links} == {
        ("Lave-linge", "Sèche-linge")
    }


def test_a_cycle_started_before_the_other_appliance_has_no_link() -> None:
    """Séchage du linge de la veille à 8 h, lessive à 10 h, séchage à 14 h : seul le second
    séchage suit la lessive."""
    actual = {
        "heure_maj_iso": iso(18),
        "equipements_reels_horaire": {
            "Lave-linge": [segment(iso(10), iso(12), 0.5)],
            "Sèche-linge": [segment(iso(8), iso(9), 1.0), segment(iso(14), iso(16), 1.0)],
        },
    }
    timeline = build_timeline({"planning": []}, actual, 18.0, 10.0, 8.0, LAUNDRY)
    assert [row.device for row in timeline.rows] == ["Lave-linge", "Sèche-linge"]
    assert [(link.from_hour, link.to_hour) for link in timeline.links] == [(12.0, 14.0)]


def test_a_launched_planned_cycle_is_linked_from_its_measured_start() -> None:
    """Lessive prévue à 10 h, lancée à 10 h 20 et finie ; séchage prévu à 13 h, lancé à
    13 h 10 : la liaison va de la fin mesurée au départ mesuré, pleine."""
    state = {"planning": [cycle("Lave-linge", 10, 12), cycle("Sèche-linge", 13, 15)]}
    actual = {
        "heure_maj_iso": iso(13, 30),
        "equipements_reels_horaire": {
            "Lave-linge": [segment(iso(10, 20), iso(12, 15), 0.9)],
            "Sèche-linge": [segment(iso(13, 10), iso(13, 30), 0.2, running=True)],
        },
    }
    timeline = build_timeline(state, actual, 13.5, 10.0, 8.0, LAUNDRY)
    assert [(link.from_hour, link.to_hour, link.started) for link in timeline.links] == [
        (12.25, 13.1667, True)
    ]
