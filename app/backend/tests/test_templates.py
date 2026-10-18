"""Modèles prêts à l'emploi (lot 4.3) : réglages appliqués à la maison détectée."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot import configuration, profiles, templates
from wattslot.configuration import Behavior, Configuration
from wattslot.main import create_app
from wattslot.objective_settings import ObjectiveSettings, Preset
from wattslot.templates import TariffEntities

# Modèle de chaque profil d'exemple.
PROFILES = {
    "reference": "off_peak",
    "no_battery": "off_peak",
    "no_pool": "off_peak",
    "ev": "off_peak",
    "heat_pump": "off_peak",
    "two_dishwashers": "off_peak",
    "southern": "off_peak",
    "tempo": "tempo",
    "dynamic": "dynamic",
}


def test_every_profile_has_its_template() -> None:
    assert set(PROFILES) == set(profiles.names())
    assert templates.names() == ["dynamic", "off_peak", "single", "tempo"]
    for template in templates.all_templates():
        assert template.name.keys() == template.description.keys() == {"fr", "en"}


def _house_specific(found: Configuration) -> Configuration:
    """Sans les valeurs propres à la maison, que le modèle laisse aux défauts : réglages de la
    batterie et vitesses mesurées des durées de fonctionnement."""
    devices = [
        d.model_copy(update={"runtime": d.runtime.model_copy(update={"speeds": []})})
        if d.runtime is not None
        else d
        for d in found.devices
    ]
    return found.model_copy(update={"devices": devices, "battery": None})


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_each_profile_is_found_by_applying_its_template(name: str) -> None:
    profile = profiles.load(name)
    tariff = profile.configuration.tariff
    assert tariff is not None
    entities = TariffEntities.model_validate(tariff.model_dump())

    found = templates.apply(templates.load(PROFILES[name]), profile.home, Configuration(), entities)

    assert configuration.validate(profile.home, found) == []
    expected = configuration.effective(profile.home, _house_specific(profile.configuration))
    assert configuration.effective(profile.home, found) == expected


def test_settings_of_unknown_types_battery_and_objective_are_kept() -> None:
    profile = profiles.load("heat_pump")
    home = profile.home.model_copy(
        update={
            "devices": [
                d.model_copy(update={"custom_type": None}) if d.key == "heat_pump" else d
                for d in profile.home.devices
            ]
        }
    )
    objective = ObjectiveSettings(preset=Preset.AUTONOMY)
    saved = profile.configuration.model_copy(update={"objective": objective})

    found = templates.apply(templates.load("single"), home, saved)

    # Sans son type propre, la pompe à chaleur n'est connue du modèle que comme OtherLoad :
    # ses réglages enregistrés restent.
    assert found.of("heat_pump") == saved.of("heat_pump")
    assert found.battery == saved.battery and found.objective == objective
    assert found.tariff is not None and found.tariff.kind.value == "SingleTariff"


def test_a_link_to_a_type_needs_a_single_device_of_that_type() -> None:
    profile = profiles.load("reference")
    second = next(d for d in profile.home.devices if d.key == "washing_machine")
    home = profile.home.model_copy(
        update={"devices": [*profile.home.devices, second.model_copy(update={"key": "wm2"})]}
    )

    found = templates.apply(templates.load("off_peak"), home, Configuration())

    dryer = found.of("dryer")
    assert dryer is not None and dryer.behavior is Behavior.CYCLE and dryer.after is None


def test_preview_lists_the_changes(tmp_path: Path) -> None:
    profile = profiles.load("reference")
    preview = templates.preview(templates.load("tempo"), profile.home, profile.configuration)

    parts = [(c.part, c.device) for c in preview.changes]
    assert ("tariff", None) in parts and ("battery", None) not in parts
    assert ("device", "pool") in parts  # vitesses mesurées au lieu des vitesses saisies
    assert ("device", "dryer") not in parts
    assert [i.code for i in preview.issues] == ["tariff_without_color_entity"]


def test_api(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        home = profiles.load("ev").home.model_dump(mode="json")
        assert api.put("/api/home", json=home).status_code == 200
        listed = api.get("/api/templates").json()
        assert [t["key"] for t in listed] == ["dynamic", "off_peak", "single", "tempo"]
        off_peak = next(t for t in listed if t["key"] == "off_peak")
        assert "ev" in off_peak["devices"] and "solar" not in off_peak["devices"]
        assert off_peak["name"]["fr"] == "Solaire, heures creuses"

        assert api.post("/api/templates/unknown/preview").status_code == 404
        preview = api.post("/api/templates/tempo/preview").json()
        assert preview["issues"][0]["code"] == "tariff_without_color_entity"
        assert api.post("/api/templates/tempo/apply").status_code == 422
        assert api.get("/api/configuration").json()["tariff"] is None  # rien d'enregistré

        entities = {"color_entity": "sensor.tempo_today"}
        applied = api.post("/api/templates/tempo/apply", json=entities)
        assert applied.status_code == 200
        saved = api.get("/api/configuration").json()
        assert saved["tariff"]["color_entity"] == "sensor.tempo_today"
        ev = next(d for d in saved["devices"] if d["key"] == "ev")
        assert ev["behavior"] == "EnergyByDeadlineBehavior" and not ev["default"]
