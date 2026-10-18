from pathlib import Path

from fastapi.testclient import TestClient

from wattslot import home_model
from wattslot.detection import DeviceKind, Role
from wattslot.main import create_app
from wattslot.ontology import GRAPH_LIBRARY, VOCAB
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
        assert client.get("/api/home").json() == {"devices": [], "types": []}

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
