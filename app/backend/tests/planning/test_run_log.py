"""Journal des calculs : l'heure annoncée de chaque équipement, calcul après calcul."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from wattslot import report
from wattslot.detection import DeviceKind
from wattslot.home_model import HomeDevice, HomeModel
from wattslot.planning import run_log
from wattslot.storage.database import open_database

DAY = date(2026, 11, 11)


def _slot(device: str, start_min: int, *reasons: str) -> dict[str, Any]:
    return {
        "equipement": device,
        "heure_debut": start_min // 60,
        "heure_fin": start_min // 60 + 2,
        "debut_min": start_min,
        "fin_min": start_min + 120,
        "energie_kwh": 1.0,
        "explication": {"raisons": [{"code": code, "params": {}} for code in reasons]},
    }


def test_each_device_says_what_happened_to_its_start() -> None:
    plan = {
        "date_cible": DAY.isoformat(),
        "planning": [
            _slot("Lave-linge", 660, "objective"),  # même heure qu'avant
            _slot("Sèche-linge", 840, "announced_kept"),  # gardée malgré un autre départ
            _slot("Lave-vaisselle", 900, "objective"),  # déplacée
            _slot("Four", 720, "objective"),  # première annonce
            _slot("Chauffe-eau", 120, "objective"),  # non suivie, replacée
            _slot("Congélateur", 545, "launched", "objective"),  # cycle réel reconnu
        ],
    }
    announced = {
        "Lave-linge": 660,
        "Sèche-linge": 840,
        "Lave-vaisselle": 780,
        "Chauffe-eau": 60,
        "Congélateur": 540,
        "Radiateur": 600,  # plus dans le plan
    }

    found = run_log.entry(plan, announced, set(), {"Chauffe-eau"})

    assert {device: item["state"] for device, item in found.items()} == {
        "Lave-linge": "kept",
        "Sèche-linge": "kept_by_margin",
        "Lave-vaisselle": "moved",
        "Four": "new",
        "Chauffe-eau": "placed_again",
        "Congélateur": "launched",
        "Radiateur": "removed",
    }
    assert found["Lave-vaisselle"] == {"start_min": 900, "previous_min": 780, "state": "moved"}
    assert found["Radiateur"]["start_min"] is None


def test_runs_are_kept_a_few_days(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    devices = {"Lave-linge": {"start_min": 660, "previous_min": None, "state": "new"}}
    old = DAY - timedelta(days=run_log.KEPT_DAYS + 1)
    run_log.record(database, datetime(2026, 11, 3, 8, 59, tzinfo=UTC), old, False, devices)
    run_log.record(
        database, datetime(2026, 11, 10, 8, 59, tzinfo=UTC), DAY - timedelta(1), False, {}
    )
    run_log.record(database, datetime(2026, 11, 11, 8, 59, tzinfo=UTC), DAY, True, devices)

    found = run_log.recent(database)

    assert [(run["day"], run["manual"]) for run in found] == [
        ("2026-11-10", False),
        ("2026-11-11", True),
    ]
    assert found[1]["devices"] == devices
    assert [run["day"] for run in run_log.recent(database, days=1)] == ["2026-11-11"]
    (tmp_path / "empty").mkdir()
    assert run_log.recent(open_database(tmp_path / "empty")) == []


def test_the_report_gives_the_runs_without_any_device_name() -> None:
    home = HomeModel(
        devices=[
            HomeDevice(key="washer", kind=DeviceKind.WASHING_MACHINE, name="Lave-linge", sensors=[])
        ]
    )
    names = report.Anonymizer(home)
    run = {
        "at": "2026-11-11T08:59:00+00:00",
        "day": "2026-11-11",
        "manual": False,
        "devices": {
            "Lave-linge": {"start_min": 660, "previous_min": 600, "state": "moved"},
            "Ancien appareil": {"start_min": None, "previous_min": 60, "state": "removed"},
        },
    }

    found = report._run(run, names)

    assert set(found["devices"]) == {"WashingMachine_1", "équipement"}
    assert "Lave-linge" not in str(found) and "Ancien appareil" not in str(found)
    assert found["devices"]["WashingMachine_1"]["state"] == "moved"
