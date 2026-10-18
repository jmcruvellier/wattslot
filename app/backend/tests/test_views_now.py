"""« En ce moment » et prochaine action de la vue Aujourd'hui (lot 6b.3)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.test_views_day import state_of
from tests.v1_oracle import STATES
from wattslot import home_model
from wattslot.aggregation import QUARTER
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.languages import LANGUAGES
from wattslot.main import create_app
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.views.display import Context
from wattslot.views.now import TEXTS, measure_now, next_action, sentence
from wattslot.views.timeline import Timeline

ZONE = ZoneInfo("Europe/Paris")
CONTEXT = Context(zone=ZONE, off_peak=((0, 6), (22, 24)))
NOON = datetime(2026, 10, 15, 10, 7, tzinfo=UTC)  # 12 h 07 à Paris


# --- Phrase du moment -------------------------------------------------------------------------


def test_every_language_has_every_sentence() -> None:
    assert set(TEXTS) == set(LANGUAGES)
    for texts in TEXTS.values():
        assert set(texts) == set(TEXTS["fr"])
        assert "{share}" in texts["sun_share"]


@pytest.mark.parametrize(
    ("flows", "off_peak", "expected"),
    [
        (
            {"production_w": 1800, "consumption_w": 2200},
            False,
            "Le soleil couvre 82 % de la maison",
        ),
        (
            {"production_w": 3000, "consumption_w": 1000, "charge_w": 1500, "export_w": 500},
            False,
            "Le soleil couvre toute la maison, le surplus charge la batterie",
        ),
        (
            {"production_w": 3000, "consumption_w": 1000, "export_w": 2000},
            False,
            "Le soleil couvre toute la maison, le surplus part sur le réseau",
        ),
        (
            {"production_w": 0, "consumption_w": 600, "discharge_w": 550, "import_w": 50},
            False,
            "La batterie alimente la maison",
        ),
        (
            {"production_w": 10, "consumption_w": 600, "import_w": 600},
            True,
            "La maison tire sur le réseau, en heures creuses",
        ),
        (
            {"production_w": 0, "consumption_w": 600, "import_w": 600},
            False,
            "La maison tire sur le réseau, en heures pleines",
        ),
        ({"production_w": 0, "consumption_w": 0}, False, None),
        ({"consumption_w": 500}, False, None),
    ],
)
def test_sentence_follows_the_flows(
    flows: dict[str, float], off_peak: bool, expected: str | None
) -> None:
    assert sentence(flows, off_peak, "fr") == expected


def test_sentence_in_english() -> None:
    flows = {"production_w": 1800, "consumption_w": 2200}
    assert sentence(flows, False, "en") == "The sun covers 82% of the home"


# --- Flux du dernier quart d'heure ------------------------------------------------------------


class QuarterAggregator:
    """Dernier quart d'heure clos à ``until`` : énergie par compteur, en kWh."""

    def __init__(self, until: datetime, energies: dict[str, float]) -> None:
        self.until = until
        self.energies = energies

    def status(self) -> Any:
        return SimpleNamespace(complete_until={QUARTER: self.until})

    def read(self, entity_id: str, period: str, start: datetime, end: datetime) -> list[Any]:
        assert period == QUARTER and end == self.until and end - start == timedelta(minutes=15)
        kwh = self.energies.get(entity_id)
        return [] if kwh is None else [SimpleNamespace(energy_kwh=kwh, start=start)]


def _home(tmp_path: Path) -> GraphStore:
    graph = GraphStore(tmp_path)
    home_model.load_vocabulary(graph)
    devices = {
        "solar": ([("sensor.pv", Role.ENERGY_PRODUCED)], DeviceKind.SOLAR),
        "grid": (
            [("sensor.import", Role.ENERGY_IMPORTED), ("sensor.export", Role.ENERGY_EXPORTED)],
            DeviceKind.GRID,
        ),
        "battery": (
            [("sensor.charge", Role.ENERGY_CHARGED), ("sensor.discharge", Role.ENERGY_DISCHARGED)],
            DeviceKind.BATTERY,
        ),
    }
    home_model.save(
        graph,
        HomeModel(
            devices=[
                HomeDevice(
                    key=key,
                    kind=kind,
                    name=key,
                    sensors=[HomeSensor(entity_id=e, role=r) for e, r in sensors],
                )
                for key, (sensors, kind) in devices.items()
            ]
        ),
    )
    return graph


def _ingestor(soc: float | None) -> Any:
    entities = [SimpleNamespace(role=Role.STATE_OF_CHARGE, last_value=soc)]
    return SimpleNamespace(status=lambda: SimpleNamespace(entities=entities))


def test_flows_of_the_last_closed_quarter(tmp_path: Path) -> None:
    until = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    # Sur 15 minutes : 0,45 kWh produits (1 800 W), 0,1 acheté (400 W), 0,05 rendu par la batterie.
    aggregator = QuarterAggregator(
        until,
        {"sensor.pv": 0.45, "sensor.import": 0.1, "sensor.discharge": 0.05, "sensor.export": 0.0},
    )
    state = SimpleNamespace(aggregator=aggregator, ingestor=_ingestor(64.4), graph=_home(tmp_path))
    found = measure_now(state, NOON, CONTEXT, "fr")
    assert (found.since, found.until) == (until - timedelta(minutes=15), until)
    assert (found.production_w, found.consumption_w) == (1800, 2400)
    assert (found.battery_w, found.grid_w, found.soc_percent) == (-200, 400, 64)
    assert found.off_peak is False
    assert found.sentence == "Le soleil couvre 75 % de la maison"


def test_no_flows_when_the_last_quarter_is_too_old(tmp_path: Path) -> None:
    until = NOON - timedelta(minutes=45)
    state = SimpleNamespace(
        aggregator=QuarterAggregator(until, {"sensor.pv": 0.45}),
        ingestor=_ingestor(50.0),
        graph=_home(tmp_path),
    )
    found = measure_now(state, NOON, CONTEXT, "fr")
    assert (found.production_w, found.sentence, found.soc_percent) == (None, None, 50)


def test_no_flows_without_home_assistant() -> None:
    state = SimpleNamespace(aggregator=None, ingestor=None)
    night = datetime(2026, 10, 15, 21, 30, tzinfo=UTC)  # 23 h 30 à Paris, heures creuses
    found = measure_now(state, night, CONTEXT, "fr")
    assert found.model_dump(exclude_none=True) == {"off_peak": True}


# --- Prochaine action -------------------------------------------------------------------------


def _timeline(*statuses: tuple[str, str, int, int]) -> Timeline:
    return Timeline.model_validate(
        {
            "rows": [
                {"device": "Lave-linge", "kind": "cycle", "planned": [], "actual": []},
                {"device": "Lave-vaisselle", "kind": "cycle", "planned": [], "actual": []},
                {"device": "Piscine", "kind": "runtime", "planned": [], "actual": []},
            ],
            "empty": None,
            "production_kwh": 10.0,
            "consumption_kwh": 8.0,
            "statuses": [
                {
                    "device": device,
                    "status": status,
                    "planned_start_min": start,
                    "planned_end_min": end,
                    "planned_kwh": 1.0,
                }
                for device, status, start, end in statuses
            ],
            "unplanned": [],
            "badge": None,
        }
    )


def test_next_action_is_the_next_cycle_still_to_start() -> None:
    timeline = _timeline(
        ("Lave-vaisselle", "on_time", 600, 700),  # déjà lancé
        ("Piscine", "planned", 700, 900),  # pas un cycle
        ("Lave-linge", "planned", 780, 900),
        ("Lave-vaisselle", "planned", 1320, 1400),
    )
    explanations = {"Lave-linge": "Au plus fort du soleil."}
    found = next_action(timeline, explanations, NOON, CONTEXT)
    assert found is not None
    assert (found.device, found.start_min, found.end_min) == ("Lave-linge", 780, 900)
    assert found.explanation == "Au plus fort du soleil."


def test_next_action_while_its_slot_is_running_then_none() -> None:
    timeline = _timeline(("Lave-linge", "planned", 700, 760))  # 11 h 40 - 12 h 40
    found = next_action(timeline, {}, NOON, CONTEXT)
    assert found is not None and found.explanation is None
    late = datetime(2026, 10, 15, 11, 0, tzinfo=UTC)  # 13 h, plage finie
    assert next_action(timeline, {}, late, CONTEXT) is None


# --- Route ------------------------------------------------------------------------------------


def test_today_view_carries_now_and_next_action_other_days_do_not(tmp_path: Path) -> None:
    today = {**state_of(STATES[0]), "date_cible": date.today()}
    with TestClient(create_app(_settings(tmp_path))) as client:
        store = PlanStore(open_database(tmp_path / "data"))
        store.save("today", today["date_cible"], today, 1.0, False)
        store.save("yesterday", today["date_cible"] - timedelta(days=1), today, 1.0, False)
        found = client.get("/api/views/today").json()
        other = client.get("/api/views/yesterday").json()
    assert found["now"]["sentence"] is None  # sans Home Assistant, pas de flux
    assert "next_action" in found
    assert other["now"] is None and other["next_action"] is None
