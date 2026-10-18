from pathlib import Path

from fastapi.testclient import TestClient

from wattslot import __version__
from wattslot.ingress import SUPERVISOR_INGRESS_ADDRESS
from wattslot.main import create_app
from wattslot.runtime import RunMode, Settings
from wattslot.storage.database import DATABASE_FILENAME
from wattslot.storage.graph import GRAPH_DIRNAME


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "mode": RunMode.STANDALONE,
        "data_dir": tmp_path / "data",
        "static_dir": None,
        "home_assistant": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_health_without_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "version": __version__,
        "mode": "standalone",
        "connections": {
            "home_assistant": {"state": "not_configured", "version": None, "error": None}
        },
    }


def test_startup_creates_the_data_directory(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with TestClient(create_app(settings)):
        pass

    assert (settings.data_dir / DATABASE_FILENAME).is_file()
    assert (settings.data_dir / GRAPH_DIRNAME).is_dir()


def test_health_reports_addon_mode(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, mode=RunMode.ADDON))
    with TestClient(app, client=(SUPERVISOR_INGRESS_ADDRESS, 50000)) as client:
        assert client.get("/api/health").json()["mode"] == "addon"


def test_serves_the_interface_when_built(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<p>interface</p>", encoding="utf-8")

    with TestClient(create_app(_settings(tmp_path, static_dir=static_dir))) as client:
        assert client.get("/").text == "<p>interface</p>"
        assert client.get("/api/health").status_code == 200


def test_version_is_the_one_of_pyproject() -> None:
    """Une seule source pour la version (lot 6t.1) : celle de pyproject.toml."""
    import tomllib

    from wattslot import __version__

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert __version__ == tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
