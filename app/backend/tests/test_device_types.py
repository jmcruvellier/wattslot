"""Types d'équipements propres à l'installation (lot 2t.1) : sous-types d'un type de la
bibliothèque, enregistrés dans le graphe de la maison, calculés comme leur parent."""

from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.v1_oracle import STATES, load
from wattslot import home_model, profiles
from wattslot.detection import DeviceKind
from wattslot.home_model import DeviceType, HomeDevice, HomeModel, problems, type_key
from wattslot.main import create_app
from wattslot.planning.assemble import configured
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import from_v1
from wattslot.planning.problem import from_input
from wattslot.storage.graph import GraphStore

HEAT_PUMP = profiles.load("heat_pump")
PUMP_TYPE = DeviceType(key="heat_pump", name="Pompe à chaleur", parent=DeviceKind.OTHER_LOAD)


def device(key: str, kind: DeviceKind, custom: str | None = None) -> HomeDevice:
    return HomeDevice(key=key, kind=kind, name=key, sensors=[], custom_type=custom)


def test_problems_of_the_types() -> None:
    model = HomeModel(
        devices=[
            device("a", DeviceKind.OTHER_LOAD, "heat_pump"),
            device("b", DeviceKind.DRYER, "heat_pump"),
            device("c", DeviceKind.DRYER, "nowhere"),
        ],
        types=[PUMP_TYPE, PUMP_TYPE, DeviceType(key="link", name="Lien", parent=DeviceKind.GRID)],
    )

    found = [(code, key) for code, key, _ in problems(model)]

    assert found == [
        ("duplicate_type", "heat_pump"),
        ("type_parent_not_allowed", "link"),
        ("type_kind_mismatch", "b"),
        ("type_unknown", "c"),
    ]
    assert problems(HEAT_PUMP.home) == []
    assert type_key("Pompe à chaleur", [PUMP_TYPE]) == "pompe-a-chaleur"
    assert (
        type_key("Heat pump", [DeviceType(key="heat-pump", name="x", parent=DeviceKind.OTHER_LOAD)])
        == "heat-pump-2"
    )


def test_types_are_saved_in_the_home_graph(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    home_model.save(graph, HEAT_PUMP.home)

    loaded = home_model.load(graph)
    assert loaded.types == [PUMP_TYPE]
    pump = next(d for d in loaded.devices if d.key == "heat_pump")
    assert (pump.kind, pump.custom_type) == (DeviceKind.OTHER_LOAD, "heat_pump")


def test_a_custom_type_plans_like_its_parent() -> None:
    state, _ = load(STATES[11])
    data = from_v1(state)
    plain_home = HEAT_PUMP.home.model_copy(
        update={
            "types": [],
            "devices": [d.model_copy(update={"custom_type": None}) for d in HEAT_PUMP.home.devices],
        }
    )

    with_type = plan_day(from_input(configured(data, HEAT_PUMP.home, HEAT_PUMP.configuration)))
    as_parent = plan_day(from_input(configured(data, plain_home, HEAT_PUMP.configuration)))

    assert "Pompe à chaleur" in {r.device for r in with_type.day.runtimes}
    assert with_type.output == as_parent.output


def test_types_api(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        model = HEAT_PUMP.home.model_copy(update={"types": []})
        model = model.model_copy(
            update={"devices": [d.model_copy(update={"custom_type": None}) for d in model.devices]}
        )
        assert api.put("/api/home", json=model.model_dump(mode="json")).status_code == 200

        listed = api.get("/api/home/types").json()
        assert "GridConnection" not in listed["parents"] and listed["types"] == []
        washer = next(t for t in listed["library"] if t["kind"] == "WashingMachine")
        assert washer == {
            "kind": "WashingMachine",
            "behaviors": ["CycleBehavior", "UncontrolledBehavior"],
            "roles": ["PowerConsumed", "EnergyConsumed"],
            "subtypes": True,
        }
        assert len(listed["library"]) == 9
        created = api.post(
            "/api/home/types", json={"name": "Pompe à chaleur", "parent": "OtherLoad"}
        )
        assert created.json() == {
            "key": "pompe-a-chaleur",
            "name": "Pompe à chaleur",
            "parent": "OtherLoad",
        }
        refused = api.post("/api/home/types", json={"name": "Lien", "parent": "GridConnection"})
        assert refused.status_code == 422

        # L'équipement prend le type ; un enregistrement qui ne connaît pas les types le garde.
        devices = [
            {
                **d.model_dump(mode="json"),
                **({"custom_type": "pompe-a-chaleur"} if d.key == "heat_pump" else {}),
            }
            for d in model.devices
        ]
        assert api.put("/api/home", json={"devices": devices}).status_code == 200
        unaware = [{k: v for k, v in d.items() if k != "custom_type"} for d in devices]
        assert api.put("/api/home", json={"devices": unaware}).status_code == 200
        saved = api.get("/api/home").json()
        assert [t["key"] for t in saved["types"]] == ["pompe-a-chaleur"]
        pump = next(d for d in saved["devices"] if d["key"] == "heat_pump")
        assert pump["custom_type"] == "pompe-a-chaleur"

        mismatch = [{**d, "kind": "Dryer"} if d["key"] == "heat_pump" else d for d in devices]
        assert api.put("/api/home", json={"devices": mismatch}).status_code == 422

        renamed = api.patch("/api/home/types/pompe-a-chaleur", json={"name": "PAC"})
        assert renamed.json()["name"] == "PAC"
        in_use = api.delete("/api/home/types/pompe-a-chaleur")
        assert in_use.status_code == 409 and in_use.json()["detail"]["devices"] == ["heat_pump"]
        assert api.delete("/api/home/types/nowhere").status_code == 404
        assert (
            api.put("/api/home", json={"devices": unaware, "types": saved["types"]}).status_code
            == 200
        )
        without = [{**d, "custom_type": None} for d in unaware]
        assert api.put("/api/home", json={"devices": without}).status_code == 200
        assert api.delete("/api/home/types/pompe-a-chaleur").status_code == 204
        assert api.get("/api/home/types").json()["types"] == []


def test_ha_sensors_offered_for_a_device_added_by_hand(tmp_path: Path) -> None:
    from wattslot.detection import Role, sensor_choices
    from wattslot.home_assistant import HomeSnapshot

    def state(unit: str | None, name: str = "x") -> dict[str, object]:
        return {"attributes": {"unit_of_measurement": unit, "friendly_name": name}}

    snapshot = HomeSnapshot(
        states={
            "sensor.pump_energy": state("kWh", "Pompe"),
            "sensor.pump_power": state("W"),
            "sensor.battery_level": state("%"),
            "sensor.temperature": state("°C"),
            "switch.pump": state(None),
        }
    )

    found = {c.entity_id: c for c in sensor_choices(snapshot)}

    assert set(found) == {"sensor.pump_energy", "sensor.pump_power", "sensor.battery_level"}
    assert Role.ENERGY_CONSUMED in found["sensor.pump_energy"].roles
    assert found["sensor.pump_power"].roles == sorted({Role.POWER_CONSUMED, Role.POWER_PRODUCED})
    assert found["sensor.battery_level"].roles == [Role.STATE_OF_CHARGE]
    assert found["sensor.pump_energy"].name == "Pompe"
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/home/entities").status_code == 503
