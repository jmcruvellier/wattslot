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
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, Phase, Supply
from wattslot.languages import LANGUAGES
from wattslot.main import create_app
from wattslot.planning.plan import Alternative, Explanation, Reason
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


def test_without_panels_the_home_is_on_the_grid_or_the_battery() -> None:
    """Sans panneaux, pas de production mesurée : la phrase parle du réseau ou de la batterie au
    lieu de laisser la place au texte du plan (essai d'installation du 21/10/2026)."""
    assert sentence({"consumption_w": 500, "import_w": 500}, True, "fr", solar=False) == (
        "La maison tire sur le réseau, en heures creuses"
    )
    assert sentence({"consumption_w": 500, "import_w": 500}, True, "fr") is None


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
    assert found.model_dump(exclude_none=True) == {"off_peak": True, "batteries": []}


# --- Plusieurs batteries ----------------------------------------------------------------------


def _two_batteries(tmp_path: Path) -> GraphStore:
    graph = GraphStore(tmp_path)
    home_model.load_vocabulary(graph)

    def battery(key: str, name: str, capacity: float | None, phase: Phase | None) -> HomeDevice:
        return HomeDevice(
            key=key,
            kind=DeviceKind.BATTERY,
            name=name,
            capacity_kwh=capacity,
            phase=phase,
            sensors=[
                HomeSensor(entity_id=f"sensor.{key}_soc", role=Role.STATE_OF_CHARGE),
                HomeSensor(entity_id=f"sensor.{key}_in", role=Role.ENERGY_CHARGED),
                HomeSensor(entity_id=f"sensor.{key}_out", role=Role.ENERGY_DISCHARGED),
            ],
        )

    home_model.save(
        graph,
        HomeModel(
            supply=Supply.THREE,
            devices=[
                battery("small", "Petite batterie", 2.0, Phase.L2),
                battery("large", "Grande batterie", 6.0, Phase.L3),
                HomeDevice(
                    key="grid",
                    kind=DeviceKind.GRID,
                    name="Réseau",
                    sensors=[HomeSensor(entity_id="sensor.import", role=Role.ENERGY_IMPORTED)],
                ),
            ],
        ),
    )
    return graph


def _levels(**soc: float) -> Any:
    entities = [
        SimpleNamespace(role=Role.STATE_OF_CHARGE, entity_id=f"sensor.{key}_soc", last_value=value)
        for key, value in soc.items()
    ]
    return SimpleNamespace(status=lambda: SimpleNamespace(entities=entities))


def test_each_battery_has_its_own_level_and_the_home_their_weighted_mean(tmp_path: Path) -> None:
    until = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    # Sur 15 minutes : la petite charge 0,1 kWh (400 W), la grande rend 0,25 kWh (1 000 W).
    aggregator = QuarterAggregator(
        until,
        {
            "sensor.small_in": 0.1,
            "sensor.large_out": 0.25,
            "sensor.large_in": 0.0,
            "sensor.import": 0.05,
        },
    )
    state = SimpleNamespace(
        aggregator=aggregator,
        ingestor=_levels(small=40.0, large=80.0),
        graph=_two_batteries(tmp_path),
    )

    found = measure_now(state, NOON, CONTEXT, "fr")

    # 2 kWh à 40 % et 6 kWh à 80 % : 70 % pour la maison, pas les 40 % du premier capteur.
    assert found.soc_percent == 70
    by_name = {battery.name: battery for battery in found.batteries}
    small, large = by_name["Petite batterie"], by_name["Grande batterie"]
    assert (small.soc_percent, small.stored_kwh, small.power_w) == (40.0, 0.8, 400)
    assert (large.soc_percent, large.stored_kwh, large.power_w) == (80.0, 4.8, -1000)
    assert (small.phase, large.phase) == (Phase.L2, Phase.L3)
    assert found.battery_w == -600


def test_a_battery_without_a_reading_is_listed_without_a_level(tmp_path: Path) -> None:
    state = SimpleNamespace(
        aggregator=None, ingestor=_levels(large=80.0), graph=_two_batteries(tmp_path)
    )

    found = measure_now(state, NOON, CONTEXT, "fr")

    assert found.soc_percent == 80  # la seule batterie mesurée
    assert {b.name: b.soc_percent for b in found.batteries} == {
        "Petite batterie": None,
        "Grande batterie": 80.0,
    }


def test_three_batteries_of_different_sizes(tmp_path: Path) -> None:
    """Trois batteries de 3,6, 4 et 10 kWh à 23, 24 et 48 % : 37 % pour la maison. La tuile
    affichait les 24 % d'une seule (issue 52)."""
    graph = GraphStore(tmp_path)
    home_model.load_vocabulary(graph)
    sizes = {"portable": 3.6, "second": 4.0, "large": 10.0}
    home_model.save(
        graph,
        HomeModel(
            devices=[
                HomeDevice(
                    key=key,
                    kind=DeviceKind.BATTERY,
                    name=key,
                    capacity_kwh=capacity,
                    sensors=[HomeSensor(entity_id=f"sensor.{key}_soc", role=Role.STATE_OF_CHARGE)],
                )
                for key, capacity in sizes.items()
            ]
        ),
    )
    # L'ordre des relevés n'est pas celui des batteries : la plus grosse n'est pas la première.
    state = SimpleNamespace(
        aggregator=None, ingestor=_levels(second=24.0, portable=23.0, large=48.0), graph=graph
    )

    found = measure_now(state, NOON, CONTEXT, "fr")

    assert found.soc_percent == 37
    assert [b.soc_percent for b in found.batteries] == [48.0, 23.0, 24.0]  # triées par clé
    assert [b.stored_kwh for b in found.batteries] == [4.8, 0.83, 0.96]


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


def test_next_action_offers_the_other_starts_still_to_come() -> None:
    timeline = _timeline(("Lave-linge", "planned", 1260, 1402))
    detail = Explanation(
        reasons=[Reason(code="full_charge_first")],
        alternatives=[
            Alternative(start_min=1200, cost_eur_delta=-0.099, import_kwh_delta=-0.732),
            Alternative(start_min=600, cost_eur_delta=-0.2, import_kwh_delta=-1.0),  # passé
        ],
    )

    found = next_action(timeline, {}, NOON, CONTEXT, {"Lave-linge": detail})

    assert found is not None and not found.chosen
    assert [(a.start_min, a.end_min, a.cost_eur_delta) for a in found.alternatives] == [
        (1200, 1342, -0.099)
    ]


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
