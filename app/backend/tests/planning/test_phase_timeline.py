"""Maison en triphasé : une ligne par groupe de batteries dans la frise, là où la prévision de
chaque groupe est réelle (batteries qui ne compensent que leur phase)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.planning.test_actual import DAY, at, reading
from tests.planning.test_phase_battery import BASE, battery, home, on_phase_2
from tests.test_views_day import V1_CONTEXT
from wattslot.battery_settings import BatterySettings
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, Phase, Supply
from wattslot.planning.actual import actual_day
from wattslot.planning.engine import plan_day
from wattslot.planning.merge import merge_plans
from wattslot.planning.plan import BATTERY, Plan
from wattslot.planning.store import dumps, loads
from wattslot.storage.raw import RawStores
from wattslot.views.day import battery_curves
from wattslot.views.timeline import build_timeline


def stored(found: Any) -> dict[str, Any]:
    """Plan tel qu'il est enregistré puis relu."""
    plan: dict[str, Any] = loads(dumps(plan_day(found, explained=False).day.to_v1()))
    return plan


def battery_item(plan: dict[str, Any]) -> dict[str, Any]:
    return next(item for item in plan["planning"] if item["equipement"] == BATTERY)


def two_phases(sun_kwh: float = 1.5) -> Any:
    """Une batterie vide sur la phase 2 (avec le solaire), une pleine sur la phase 3."""
    lines = {Phase.L2: battery(5.0, 0.0), Phase.L3: battery(5.0, 5.0)}
    return replace(
        home(BASE, sun_kwh=sun_kwh),
        battery=battery(10.0, 5.0),
        line_batteries=lines,
        shared_battery=replace(battery(5.0, 0.0), capacity_kwh=0.0, stored_kwh=0.0),
    )


# --- Plan -----------------------------------------------------------------------------------------


def test_a_plan_on_the_whole_home_has_no_battery_groups() -> None:
    whole = stored(replace(home(BASE, sun_kwh=1.5), battery=battery(5.0, 2.0)))

    assert "groupes" not in battery_item(whole)


def test_the_plan_keeps_the_forecast_of_each_group() -> None:
    item = battery_item(stored(two_phases()))

    groups = {group["phase"]: group["mouvements"] for group in item["groupes"]}
    assert set(groups) == {2, 3}  # pas de groupe « total » : aucune batterie ne le compense
    at_ten = {phase: next(m for m in found if m["heure"] == 10) for phase, found in groups.items()}
    # À 10 h : la phase 2 charge son surplus, la phase 3 se décharge sur son déficit.
    assert (at_ten[2]["action"], at_ten[2]["energie_kwh"]) == ("charge", 1.3)
    assert (at_ten[3]["action"], at_ten[3]["energie_kwh"]) == ("decharge", 0.3)
    # La ligne de toutes les batteries reste leur somme.
    whole = next(m for m in item["mouvements"] if m["heure"] == 10)
    assert (whole["action"], whole["energie_kwh"]) == ("charge", 1.0)
    assert Plan.from_v1(stored(two_phases())).battery is not None


def test_the_batteries_that_offset_the_total_are_a_group_of_their_own() -> None:
    found = replace(two_phases(), shared_battery=battery(5.0, 4.0), battery=battery(15.0, 9.0))

    phases = [group["phase"] for group in battery_item(stored(found))["groupes"]]

    assert phases == [2, 3, 0]


def test_groups_are_merged_hour_by_hour() -> None:
    old, new = stored(two_phases(sun_kwh=1.5)), stored(two_phases(sun_kwh=3.0))

    merged = battery_item(merge_plans(new, old, 11))

    phase_2 = next(g for g in merged["groupes"] if g["phase"] == 2)["mouvements"]
    by_hour = {m["heure"]: m["energie_kwh"] for m in phase_2}
    assert by_hour[10] == 1.3  # avant 11 h : l'ancien plan
    assert by_hour[11] == pytest.approx(2.5)  # ensuite : le nouveau, à pleine puissance
    # Le nouveau plan ne distingue plus les phases : la ligne unique revient.
    whole = stored(replace(home(BASE, sun_kwh=1.5), battery=battery(5.0, 2.0)))
    assert "groupes" not in battery_item(merge_plans(whole, old, 11))


# --- Frise ----------------------------------------------------------------------------------------


def test_the_timeline_has_one_row_per_group() -> None:
    plan = stored(two_phases())
    actual = {
        "batterie_reelle_segments_par_phase": {
            2: [
                {
                    "action": "charge",
                    "debut_iso": at(10).isoformat(),
                    "fin_iso": at(11).isoformat(),
                    "energie_kwh": 1.2,
                }
            ]
        }
    }

    rows = [
        r
        for r in build_timeline(plan, actual, 15.0, 6.0, 24.0, V1_CONTEXT).rows
        if r.kind == "battery"
    ]

    assert [(row.device, row.phase) for row in rows] == [("Batterie 2", 2), ("Batterie 3", 3)]
    charge = next(bar for bar in rows[0].planned if bar.action == "charge")
    assert (charge.start_hour, charge.end_hour) == (10, 14)
    assert [(bar.action, bar.energy_kwh) for bar in rows[0].actual] == [("charge", 1.2)]
    assert rows[1].actual == [] and all(bar.action == "discharge" for bar in rows[1].planned)


def test_the_timeline_keeps_a_single_row_on_the_whole_home() -> None:
    plan = stored(on_phase_2(home(BASE, sun_kwh=1.5), battery(5.0, 0.0)))
    whole = stored(replace(home(BASE, sun_kwh=1.5), battery=battery(5.0, 2.0)))

    def battery_rows(found: dict[str, Any]) -> list[tuple[str, int | None]]:
        rows = build_timeline(found, None, 15.0, 6.0, 24.0, V1_CONTEXT).rows
        return [(row.device, row.phase) for row in rows if row.kind == "battery"]

    assert battery_rows(plan) == [("Batterie 2", 2)]
    assert battery_rows(whole) == [("Batterie", None)]


# --- Mesures du jour ------------------------------------------------------------------------------


def storage(key: str, phase: Phase | None) -> HomeDevice:
    return HomeDevice(
        key=key,
        kind=DeviceKind.BATTERY,
        name=key,
        phase=phase,
        capacity_kwh=5.0,
        sensors=[
            HomeSensor(entity_id=f"sensor.{key}_in", role=Role.ENERGY_CHARGED),
            HomeSensor(entity_id=f"sensor.{key}_out", role=Role.ENERGY_DISCHARGED),
        ],
    )


MODEL = HomeModel(
    supply=Supply.THREE,
    devices=[storage("garage", Phase.L2), storage("cellar", Phase.L3), storage("meter", Phase.L1)],
)
# La batterie « meter » suit un compteur triphasé : elle compense le total, pas sa phase.
SETTINGS = Configuration(
    devices=[
        DeviceSettings(
            key="meter", behavior=Behavior.STORAGE, battery=BatterySettings(all_phases=True)
        )
    ]
)


def test_real_battery_segments_of_each_group(tmp_path: Path) -> None:
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            reading("garage", "sensor.garage_in", 10.0, at(-1)),
            reading("garage", "sensor.garage_in", 10.0, at(10)),
            reading("garage", "sensor.garage_in", 11.5, at(11)),
            reading("cellar", "sensor.cellar_out", 4.0, at(-1)),
            reading("cellar", "sensor.cellar_out", 4.0, at(11)),
            reading("cellar", "sensor.cellar_out", 4.6, at(12)),
            reading("meter", "sensor.meter_in", 2.0, at(-1)),
            reading("meter", "sensor.meter_in", 2.0, at(8)),
            reading("meter", "sensor.meter_in", 2.9, at(9)),
        ]
    )

    found = actual_day(MODEL, raw, DAY, at(13), configuration=SETTINGS)
    single = actual_day(
        MODEL.model_copy(update={"supply": Supply.SINGLE}), raw, DAY, at(13), configuration=SETTINGS
    )

    by_phase = found["batterie_reelle_segments_par_phase"]
    assert {
        p: [(s["action"], s["energie_kwh"]) for s in segments] for p, segments in by_phase.items()
    } == {
        0: [("charge", 0.9)],
        2: [("charge", 1.5)],
        3: [("decharge", 0.6)],
    }
    # Toutes ensemble : inchangé.
    assert [s["action"] for s in found["batterie_reelle_segments"]] == [
        "charge",
        "charge",
        "decharge",
    ]
    # En monophasé, aucune batterie n'est sur une phase : rien par phase.
    assert "batterie_reelle_segments_par_phase" not in single


# --- Mesuré par batterie --------------------------------------------------------------------------


def test_real_battery_segments_of_each_battery(tmp_path: Path) -> None:
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            reading("garage", "sensor.garage_in", 10.0, at(-1)),
            reading("garage", "sensor.garage_in", 10.0, at(10)),
            reading("garage", "sensor.garage_in", 11.5, at(11)),
            reading("cellar", "sensor.cellar_out", 4.0, at(-1)),
            reading("cellar", "sensor.cellar_out", 4.0, at(11)),
            reading("cellar", "sensor.cellar_out", 4.6, at(12)),
        ]
    )

    found = actual_day(MODEL, raw, DAY, at(13), configuration=SETTINGS)
    single = actual_day(
        MODEL.model_copy(update={"supply": Supply.SINGLE}), raw, DAY, at(13), configuration=SETTINGS
    )
    alone = actual_day(HomeModel(devices=MODEL.devices[:1]), raw, DAY, at(13))

    def each(day: dict[str, Any]) -> list[tuple[str, int, list[tuple[str, float]]]]:
        return [
            (b["cle"], b["phase"], [(s["action"], s["energie_kwh"]) for s in b["segments"]])
            for b in day["batterie_reelle_segments_par_batterie"]
        ]

    # Chacune avec son groupe : sa phase, ou 0 pour celle qui compense le total.
    assert each(found) == [
        ("garage", 2, [("charge", 1.5)]),
        ("cellar", 3, [("decharge", 0.6)]),
        ("meter", 0, []),
    ]
    # En monophasé aussi, dès qu'il y a plusieurs batteries : toutes dans le même groupe.
    assert [(key, phase) for key, phase, _ in each(single)] == [
        ("garage", 0),
        ("cellar", 0),
        ("meter", 0),
    ]
    # Une seule batterie : sa ligne suffit.
    assert "batterie_reelle_segments_par_batterie" not in alone


def _measured(key: str, phase: int, hour: int, action: str = "charge") -> dict[str, Any]:
    return {
        "cle": key,
        "nom": key.capitalize(),
        "phase": phase,
        "segments": [
            {
                "action": action,
                "debut_iso": at(hour).isoformat(),
                "fin_iso": at(hour + 1).isoformat(),
                "energie_kwh": 0.5,
            }
        ],
    }


def test_the_row_of_a_group_lists_its_batteries_when_it_has_several() -> None:
    plan = stored(two_phases())
    actual = {
        "batterie_reelle_segments_par_batterie": [
            _measured("garage", 2, 10),
            _measured("shed", 2, 10, "decharge"),
            _measured("cellar", 3, 11),
        ]
    }

    rows = {
        row.phase: row
        for row in build_timeline(plan, actual, 15.0, 6.0, 24.0, V1_CONTEXT).rows
        if row.kind == "battery"
    }

    # Phase 2 : deux batteries, chacune avec son mesuré (ici l'une se vide dans l'autre).
    assert [(b.key, b.name, [bar.action for bar in b.actual]) for b in rows[2].batteries] == [
        ("garage", "Garage", ["charge"]),
        ("shed", "Shed", ["discharge"]),
    ]
    # Phase 3 : une seule batterie, la ligne du groupe est déjà la sienne.
    assert rows[3].batteries == []


def test_the_single_battery_row_lists_every_battery() -> None:
    whole = stored(replace(home(BASE, sun_kwh=1.5), battery=battery(5.0, 2.0)))
    actual = {
        "batterie_reelle_segments_par_batterie": [
            _measured("garage", 2, 10),
            _measured("cellar", 0, 11),
        ]
    }

    def battery_row(measured: dict[str, Any] | None) -> Any:
        rows = build_timeline(whole, measured, 15.0, 6.0, 24.0, V1_CONTEXT).rows
        return next(row for row in rows if row.kind == "battery")

    # Plan sur le total (monophasé, ou triphasé sans calcul par phase) : toutes sous la ligne.
    assert [b.key for b in battery_row(actual).batteries] == ["garage", "cellar"]
    assert battery_row(None).batteries == []


# --- Courbes par groupe et par batterie -----------------------------------------------------------


def test_the_plan_keeps_the_level_of_each_group() -> None:
    groups = {group["phase"]: group for group in battery_item(stored(two_phases()))["groupes"]}

    assert groups[2]["capacite_kwh"] == 5.0 and groups[3]["capacite_kwh"] == 5.0
    # Phase 2 : vide au départ, elle charge 1,3 kWh à 10 h. Phase 3 : pleine, elle se vide.
    assert groups[2]["soc_horaire_kwh"][9] == 0.0
    assert groups[2]["soc_horaire_kwh"][10] == pytest.approx(1.3)
    assert groups[3]["soc_horaire_kwh"][0] == pytest.approx(4.7)


def test_the_level_of_each_group_is_merged_hour_by_hour() -> None:
    old, new = stored(two_phases(sun_kwh=1.5)), stored(two_phases(sun_kwh=3.0))

    merged = battery_item(merge_plans(new, old, 11))

    level = next(g for g in merged["groupes"] if g["phase"] == 2)["soc_horaire_kwh"]
    assert level[10] == pytest.approx(1.3)  # avant 11 h : l'ancien plan
    assert level[11] == new_level(new)[11]  # ensuite : le nouveau


def new_level(plan: dict[str, Any]) -> dict[int, float]:
    groups = battery_item(plan)["groupes"]
    found: dict[int, float] = next(g for g in groups if g["phase"] == 2)["soc_horaire_kwh"]
    return found


def test_real_level_of_each_battery(tmp_path: Path) -> None:
    def level(key: str) -> HomeSensor:
        return HomeSensor(entity_id=f"sensor.{key}_soc", role=Role.STATE_OF_CHARGE)

    model = MODEL.model_copy(
        update={
            "devices": [
                d.model_copy(update={"sensors": [*d.sensors, level(d.key)]})
                for d in MODEL.devices[:2]
            ]
        }
    )
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            reading("garage", "sensor.garage_soc", 40.0, at(-1)),
            reading("garage", "sensor.garage_soc", 55.0, at(10.5)),
            reading("cellar", "sensor.cellar_soc", 90.0, at(9.25)),
        ]
    )

    found = actual_day(model, raw, DAY, at(12), configuration=SETTINGS)

    garage, cellar = found["batterie_reelle_segments_par_batterie"]
    assert garage["capacite_kwh"] == 5.0 and garage["soc_pct_minuit"] == 40.0
    assert garage["soc_pct_fin_heure"] == {10: 55.0, 11: 55.0, 12: 55.0}
    # Sans relevé la veille : le premier du jour vaut pour minuit, comme pour la maison.
    assert cellar["soc_pct_minuit"] == 90.0
    assert cellar["soc_pct_fin_heure"] == {9: 90.0, 10: 90.0, 11: 90.0, 12: 90.0}


def _level(key: str, phase: int, capacity: float, by_hour: dict[int, float]) -> dict[str, Any]:
    return {
        "cle": key,
        "nom": key.capitalize(),
        "phase": phase,
        "capacite_kwh": capacity,
        "soc_pct_fin_heure": by_hour,
        "soc_pct_minuit": by_hour.get(0),
        "segments": [],
    }


def test_curves_of_each_group_then_of_its_batteries() -> None:
    plan = stored(two_phases())
    actual = {
        "batterie_reelle_segments_par_batterie": [
            _level("garage", 2, 6.0, {0: 10.0, 1: 20.0}),
            _level("shed", 2, 2.0, {0: 50.0}),
            _level("cellar", 3, 5.0, {0: 80.0, 1: 70.0}),
        ]
    }

    curves = battery_curves(plan, actual)

    assert [(c.phase, c.key) for c in curves] == [
        (2, None),
        (None, "garage"),
        (None, "shed"),
        (3, None),
    ]
    phase_2, garage, _, phase_3 = curves
    # Prévu du groupe, en % de sa capacité ; mesuré : ses batteries pondérées par leur capacité,
    # rien pour une heure où l'une d'elles n'a pas de relevé.
    assert phase_2.planned is not None and phase_2.planned[10] == pytest.approx(26.0)
    assert phase_2.actual[:2] == [20.0, None] and phase_2.midnight_percent == 20.0
    # Une batterie n'a que son mesuré.
    assert garage.planned is None and garage.name == "Garage" and garage.actual[:2] == [10.0, 20.0]
    # Groupe d'une seule batterie : sa courbe est celle de la batterie, sans ligne de plus.
    assert phase_3.actual[:2] == [80.0, 70.0]
    # Sans mesure (demain) : le prévu de chaque groupe seulement.
    later = battery_curves(plan, None)
    assert [(c.phase, c.actual) for c in later] == [(2, [None] * 24), (3, [None] * 24)]


def test_curves_of_each_battery_on_the_whole_home() -> None:
    whole = stored(replace(home(BASE, sun_kwh=1.5), battery=battery(5.0, 2.0)))
    two = [_level("garage", 0, 5.0, {0: 10.0}), _level("cellar", 0, 5.0, {0: 80.0})]

    curves = battery_curves(whole, {"batterie_reelle_segments_par_batterie": two})

    # Plan sur le total : la courbe de la maison garde le prévu, chaque batterie a son mesuré.
    assert [(c.phase, c.key, c.planned) for c in curves] == [
        (None, "garage", None),
        (None, "cellar", None),
    ]
    # Une seule batterie, ou pas de mesure : rien de plus que la courbe de la maison.
    assert battery_curves(whole, {"batterie_reelle_segments_par_batterie": two[:1]}) == []
    assert battery_curves(whole, None) == []
