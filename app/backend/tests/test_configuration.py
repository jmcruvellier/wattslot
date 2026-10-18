"""Configuration de la maison : réglages par défaut, enregistrement, validation, API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot import configuration, home_model, profiles
from wattslot.configuration import Automation, Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.main import create_app
from wattslot.storage.graph import GraphStore

HOME = HomeModel(
    devices=[
        HomeDevice(
            key="solar",
            kind=DeviceKind.SOLAR,
            name="Panneaux",
            sensors=[HomeSensor(entity_id="sensor.pv", role=Role.ENERGY_PRODUCED)],
        ),
        HomeDevice(key="heater", kind=DeviceKind.WATER_HEATER, name="Chauffe-eau", sensors=[]),
        HomeDevice(key="washer", kind=DeviceKind.WASHING_MACHINE, name="Lave-linge", sensors=[]),
        HomeDevice(key="pool", kind=DeviceKind.POOL_PUMP, name="Piscine", sensors=[]),
    ]
)


def codes(issues: list[configuration.Issue]) -> list[tuple[str, str | None]]:
    return [(i.code, i.device) for i in issues]


def test_defaults_follow_the_kind_of_device() -> None:
    found = {d.key: d for d in configuration.effective(HOME, Configuration()).devices}

    assert found["solar"].behavior is Behavior.PRODUCTION
    assert found["solar"].automation is Automation.INFORM  # observé seulement
    assert (
        found["heater"].behavior is Behavior.CYCLE
    )  # comme la v1 ; besoin d.énergie à régler (lot 3.4)
    assert found["washer"].behavior is Behavior.CYCLE
    assert found["washer"].automation is Automation.RECOMMEND
    assert found["pool"].behavior is Behavior.RUNTIME
    assert all(d.default and d.planned for d in found.values())
    assert configuration.validate(HOME, configuration.effective(HOME, Configuration())) == []


def test_saved_settings_survive_a_new_home_model(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home_model.load_vocabulary(graph)
    home_model.save(graph, HOME)
    wanted = Configuration(
        devices=[
            DeviceSettings(
                key="pool", behavior=Behavior.UNCONTROLLED, automation=Automation.INFORM
            ),
            DeviceSettings(key="washer", behavior=Behavior.CYCLE, planned=False),
        ]
    )

    configuration.save(graph, wanted)
    home_model.save(graph, HOME)  # réenregistrer la maison n'efface pas la configuration

    assert configuration.load(graph) == wanted
    found = {d.key: d for d in configuration.effective(HOME, configuration.load(graph)).devices}
    assert found["pool"].behavior is Behavior.UNCONTROLLED and not found["pool"].default
    assert found["washer"].planned is False
    assert found["heater"].default  # rien d'enregistré : réglages par défaut

    # Équipement retiré de la maison : ses réglages ne sont plus proposés.
    smaller = HomeModel(devices=[d for d in HOME.devices if d.key != "pool"])
    assert [d.key for d in configuration.effective(smaller, configuration.load(graph)).devices] == [
        "solar",
        "heater",
        "washer",
    ]


def test_defaults_are_not_written(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    configuration.save(graph, configuration.effective(HOME, Configuration()))
    assert configuration.load(graph) == Configuration()


def test_validation_reports_each_problem() -> None:
    proposed = Configuration(
        version=99,
        devices=[
            DeviceSettings(key="ghost", behavior=Behavior.CYCLE),
            DeviceSettings(key="washer", behavior=Behavior.STORAGE),
            DeviceSettings(key="washer", behavior=Behavior.CYCLE),
            DeviceSettings(key="solar", behavior=Behavior.PRODUCTION),  # observé : pas recommandé
            DeviceSettings(key="heater", behavior=Behavior.CYCLE, automation=Automation.CONTROL),
        ],
    )

    issues = configuration.validate(HOME, proposed)

    assert codes(issues) == [
        ("unsupported_version", None),
        ("unknown_device", "ghost"),
        ("behavior_not_allowed", "washer"),
        ("duplicate_device", "washer"),
        ("observed_automation", "solar"),
        ("automation_not_available", "heater"),
    ]
    assert issues[2].params["allowed"] == "CycleBehavior, UncontrolledBehavior"


def test_configuration_api(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/configuration").json() == {
            "version": 1,
            "devices": [],
            "tariff": None,
            "battery": None,
            "objective": None,
        }
        api.put("/api/home", json=HOME.model_dump(mode="json"))

        defaults = api.get("/api/configuration").json()
        # Ordre du modèle de la maison relu (type, puis clé).
        assert [d["key"] for d in defaults["devices"]] == ["pool", "solar", "washer", "heater"]
        assert all(d["default"] for d in defaults["devices"])

        bad = {"devices": [{"key": "washer", "behavior": "StorageBehavior"}]}
        check = api.post("/api/configuration/validate", json=bad).json()
        assert [i["code"] for i in check["issues"]] == ["behavior_not_allowed"]
        refused = api.put("/api/configuration", json=bad)
        assert refused.status_code == 422
        assert refused.json()["detail"][0]["code"] == "behavior_not_allowed"

        good = {"devices": [{"key": "washer", "behavior": "CycleBehavior", "planned": False}]}
        saved = api.put("/api/configuration", json=good).json()
        washer = next(d for d in saved["devices"] if d["key"] == "washer")
        assert washer == {
            "key": "washer",
            "behavior": "CycleBehavior",
            "automation": "RecommendAutomation",
            "planned": False,
            "default": False,
            "runtime": None,
            "panels": None,
            "energy": None,
            "constraints": [],
            "after": None,
            "max_delay_days": None,
            "recurrence": None,
        }
        assert api.get("/api/configuration").json() == saved


@pytest.mark.parametrize("name", profiles.names())
def test_default_settings_are_valid_for_every_profile(name: str) -> None:
    """Lot 4.7 : qui ne déplie aucun réglage avancé enregistre les réglages par défaut, valides."""
    home = profiles.load(name).home
    defaults = configuration.effective(home, Configuration())
    assert all(settings.default for settings in defaults.devices)
    assert configuration.validate(home, defaults) == []
