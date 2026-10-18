"""Export et import de la maison (lot 3.8) : fichier JSON versionné, vérifié avant import."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot import configuration, exchange, home_model, profiles
from wattslot.main import create_app
from wattslot.storage.graph import GraphStore

REFERENCE = profiles.load("reference")


def document() -> dict[str, Any]:
    found: dict[str, Any] = json.loads(
        exchange.export(REFERENCE.home, REFERENCE.configuration).model_dump_json()
    )
    return found


def stored(tmp_path: Path) -> dict[str, Any]:
    """Export de la maison de référence telle que le graphe la relit (ordre du graphe)."""
    graph = GraphStore(tmp_path / "expected")
    home_model.save(graph, REFERENCE.home)
    configuration.save(graph, REFERENCE.configuration)
    found: dict[str, Any] = json.loads(
        exchange.export(home_model.load(graph), configuration.load(graph)).model_dump_json()
    )
    return found


def test_the_reference_home_survives_export_and_import(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home_model.save(graph, REFERENCE.home)
    configuration.save(graph, REFERENCE.configuration)
    exported = exchange.export(home_model.load(graph), configuration.load(graph))

    found, result = exchange.check(json.loads(exported.model_dump_json()))

    assert result.issues == [] and found is not None
    other = GraphStore(tmp_path / "other")
    home_model.save(other, found.home)
    configuration.save(other, found.configuration)
    assert home_model.load(other) == home_model.load(graph)
    assert configuration.load(other) == configuration.load(graph)
    assert exchange.export(home_model.load(other), configuration.load(other)) == exported


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda d: {**d, "format": "other"}, "import_format"),
        (lambda d: {**d, "version": exchange.VERSION + 1}, "import_version"),
        (lambda d: {**d, "version": "1"}, "import_version"),
        (lambda d: {**d, "home": {"devices": "none"}}, "import_invalid"),
    ],
)
def test_a_bad_file_is_refused(change: Any, code: str) -> None:
    found, result = exchange.check(change(document()))

    assert found is None and [i.code for i in result.issues] == [code]


def test_the_configuration_is_checked_before_import() -> None:
    bad = document()
    bad["home"]["devices"].append(dict(bad["home"]["devices"][0]))  # clé en double
    bad["configuration"]["devices"][0]["behavior"] = "RuntimeBehavior"  # chauffe-eau

    found, result = exchange.check(bad)

    assert found is None
    codes = {i.code for i in result.issues}
    assert codes == {"duplicate_device", "behavior_not_allowed", "recurrence_not_used"}
    assert exchange.check("not a document")[1].issues[0].code == "import_format"


def test_unknown_entities_are_reported_without_blocking() -> None:
    found, result = exchange.check(document(), known_entities=["sensor.solar_energy"])

    assert found is not None and result.issues == []
    assert result.unknown_entities and "sensor.solar_energy" not in result.unknown_entities


def test_files_exported_before_wattslot_are_still_imported() -> None:
    """Format « energy-optimizer/home » d'avant le renommage (lot 7.1) : même contenu."""
    found, result = exchange.check({**document(), "format": exchange.LEGACY_FORMAT})

    assert result.issues == [] and found is not None and found.format == "wattslot/home"


def test_version_1_files_are_migrated() -> None:
    """Version 1 (avant le lot 2t.1) : pas de types propres."""
    old = {**document(), "version": 1, "home": {"devices": document()["home"]["devices"]}}

    found, result = exchange.check(old)

    assert result.issues == [] and found is not None and found.home.types == []
    assert exchange.migrate(old)["version"] == exchange.VERSION == 2


def test_migrations_chain_version_by_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exchange, "VERSION", 3)
    monkeypatch.setitem(
        exchange.MIGRATIONS, 2, lambda d: {**d, "configuration": {**d["configuration"], "x": 1}}
    )

    migrated = exchange.migrate({**document(), "version": 1})

    assert migrated["version"] == 3 and migrated["configuration"]["x"] == 1
    assert migrated["home"]["types"] == []


def test_export_and_import_routes(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        checked = api.post("/api/configuration/import?dry_run=true", json=document())
        assert checked.status_code == 200 and checked.json()["applied"] is False
        assert api.get("/api/home").json()["devices"] == []  # rien d'appliqué

        applied = api.post("/api/configuration/import", json=document())
        assert applied.status_code == 200 and applied.json()["applied"] is True

        exported = api.get("/api/configuration/export")
        assert exported.headers["content-disposition"].startswith("attachment")
        assert exported.json() == stored(tmp_path)  # sans perte
        again = api.post("/api/configuration/import", json=exported.json())
        assert again.status_code == 200
        assert api.get("/api/configuration/export").json() == exported.json()
        turtle = api.get("/api/configuration/export.ttl")
        assert turtle.headers["content-type"].startswith("text/turtle")
        assert b"water_heater" in turtle.content

        refused = api.post("/api/configuration/import", json={**document(), "format": "x"})
        assert refused.status_code == 422
        assert refused.json()["detail"]["issues"][0]["code"] == "import_format"
