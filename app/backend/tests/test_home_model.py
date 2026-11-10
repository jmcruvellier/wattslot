from pathlib import Path

from fastapi.testclient import TestClient

from wattslot import home_model
from wattslot.detection import DeviceKind, Role
from wattslot.main import create_app
from wattslot.ontology import GRAPH_HOME, GRAPH_LIBRARY, VOCAB
from wattslot.runtime import RunMode, Settings
from wattslot.storage.graph import GraphStore

MODEL = home_model.HomeModel(
    devices=[
        home_model.HomeDevice(
            key="battery-1",
            kind=DeviceKind.BATTERY,
            name='Batterie "garage"',
            capacity_kwh=5.12,
            sensors=[
                home_model.HomeSensor(entity_id="sensor.battery_in", role=Role.ENERGY_CHARGED),
                home_model.HomeSensor(entity_id="sensor.battery_soc", role=Role.STATE_OF_CHARGE),
            ],
        ),
        home_model.HomeDevice(
            key="solar-1",
            kind=DeviceKind.SOLAR,
            name="Cabanon",
            sensors=[
                home_model.HomeSensor(
                    entity_id="sensor.shed_daily", role=Role.ENERGY_PRODUCED, resets_daily=True
                )
            ],
        ),
    ]
)


def test_model_round_trips_through_rdf(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    home_model.save(graph, MODEL)

    assert home_model.load(graph) == MODEL


def test_saving_replaces_the_previous_model(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home_model.save(graph, MODEL)

    home_model.save(graph, home_model.HomeModel(devices=MODEL.devices[1:]))

    assert [d.key for d in home_model.load(graph).devices] == ["solar-1"]


def test_vocabulary_is_loaded_under_the_provisional_namespace(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    home_model.load_vocabulary(graph)

    roles = {
        row["role"]
        for row in graph.select(
            f"SELECT ?role WHERE {{ GRAPH <{GRAPH_LIBRARY}> {{ ?role a <{VOCAB}Role> }} }}"
        )
    }
    assert {f"{VOCAB}{role}" for role in Role} == roles


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        mode=RunMode.STANDALONE, data_dir=tmp_path, static_dir=None, home_assistant=None
    )
    return TestClient(create_app(settings))


def test_home_api_saves_and_returns_the_model(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/api/home").json() == {
            "devices": [],
            "types": [],
            "supply": "SinglePhaseSupply",
            "meter_sums_phases": True,
        }

        response = client.put("/api/home", json=MODEL.model_dump(mode="json"))

        assert response.status_code == 200
        assert home_model.HomeModel(**client.get("/api/home").json()) == MODEL


def test_home_api_rejects_duplicate_keys(tmp_path: Path) -> None:
    duplicated = home_model.HomeModel(devices=[MODEL.devices[0], MODEL.devices[0]])

    with _client(tmp_path) as client:
        response = client.put("/api/home", json=duplicated.model_dump(mode="json"))

    assert response.status_code == 422


def test_proposals_need_home_assistant(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/api/home/proposals").status_code == 503


def test_home_features_say_what_the_home_has(tmp_path: Path) -> None:
    """Panneaux, batterie et équipements placés : l'interface n'affiche que ce qui existe."""
    washer = home_model.HomeDevice(
        key="washer",
        kind=DeviceKind.WASHING_MACHINE,
        name="Lave-linge",
        sensors=[home_model.HomeSensor(entity_id="sensor.washer", role=Role.ENERGY_CONSUMED)],
    )
    only_solar = home_model.HomeModel(devices=[MODEL.devices[1]])
    with _client(tmp_path) as client:
        unsaved = client.get("/api/home/features").json()
        client.put("/api/home", json=MODEL.model_dump(mode="json"))
        full = client.get("/api/home/features").json()
        client.put("/api/home", json=only_solar.model_dump(mode="json"))
        solar = client.get("/api/home/features").json()
        with_washer = home_model.HomeModel(devices=[*only_solar.devices, washer])
        client.put("/api/home", json=with_washer.model_dump(mode="json"))
        appliance = client.get("/api/home/features").json()

    assert unsaved == {"solar": True, "battery": True, "appliances": 0}
    assert full == {"solar": True, "battery": True, "appliances": 0}
    assert solar == {"solar": True, "battery": False, "appliances": 0}
    assert appliance["appliances"] == 1


THREE_PHASE = MODEL.model_copy(
    update={
        "supply": home_model.Supply.THREE,
        "meter_sums_phases": False,
        "devices": [
            MODEL.devices[0].model_copy(update={"phase": home_model.Phase.L2}),
            MODEL.devices[1].model_copy(update={"phase": home_model.Phase.ALL}),
        ],
    }
)


def test_supply_and_phases_round_trip_through_rdf(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    home_model.save(graph, THREE_PHASE)

    assert home_model.load(graph) == THREE_PHASE


def test_a_home_saved_before_phases_is_single_phase(tmp_path: Path) -> None:
    """Graphe d'avant ces réglages : ni alimentation ni phase, lu en monophasé."""
    graph = GraphStore(tmp_path)
    old = [
        t
        for t in home_model.to_triples(MODEL)
        if t.predicate.value not in (f"{VOCAB}supply", f"{VOCAB}meterSumsPhases")
    ]
    graph.replace_graph(GRAPH_HOME, old)

    assert home_model.load(graph) == MODEL


def test_the_grid_connection_has_no_phase(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    grid = home_model.HomeDevice(
        key="grid", kind=DeviceKind.GRID, name="Réseau", sensors=[], phase=home_model.Phase.L1
    )

    home_model.save(graph, home_model.HomeModel(devices=[grid], supply=home_model.Supply.THREE))

    assert home_model.load(graph).devices[0].phase is None


def test_home_api_keeps_supply_and_phases_a_request_does_not_carry(tmp_path: Path) -> None:
    """Une interface d'avant ces réglages enregistre la maison sans eux : ils sont gardés."""
    without = MODEL.model_dump(mode="json", exclude={"supply", "meter_sums_phases"})
    for device in without["devices"]:
        del device["phase"]
    with _client(tmp_path) as client:
        client.put("/api/home", json=THREE_PHASE.model_dump(mode="json"))

        client.put("/api/home", json=without)
        kept = home_model.HomeModel(**client.get("/api/home").json())
        cleared = THREE_PHASE.model_dump(mode="json")
        cleared["devices"][0]["phase"] = None
        client.put("/api/home", json=cleared)
        after = home_model.HomeModel(**client.get("/api/home").json())

    assert kept == THREE_PHASE
    assert after.devices[0].phase is None
