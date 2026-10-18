from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wattslot.ingress import SUPERVISOR_INGRESS_ADDRESS
from wattslot.main import create_app
from wattslot.runtime import RunMode, Settings


def _client(tmp_path: Path, mode: RunMode, address: str) -> TestClient:
    settings = Settings(mode=mode, data_dir=tmp_path, static_dir=None, home_assistant=None)
    return TestClient(create_app(settings), client=(address, 50000))


@pytest.mark.parametrize("address", [SUPERVISOR_INGRESS_ADDRESS, "127.0.0.1"])
def test_addon_accepts_ingress_and_local_requests(tmp_path: Path, address: str) -> None:
    with _client(tmp_path, RunMode.ADDON, address) as client:
        assert client.get("/api/health").status_code == 200


def test_addon_rejects_other_containers(tmp_path: Path) -> None:
    with _client(tmp_path, RunMode.ADDON, "172.30.33.5") as client:
        assert client.get("/api/health").status_code == 403


def test_standalone_accepts_any_address(tmp_path: Path) -> None:
    with _client(tmp_path, RunMode.STANDALONE, "192.0.2.10") as client:
        assert client.get("/api/health").status_code == 200


def test_interface_is_served_only_by_ingress(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<p>interface</p>", encoding="utf-8")
    settings = Settings(
        mode=RunMode.ADDON, data_dir=tmp_path / "data", static_dir=static, home_assistant=None
    )
    with TestClient(create_app(settings), client=(SUPERVISOR_INGRESS_ADDRESS, 50000)) as client:
        assert "interface" in client.get("/").text
        assert client.get("/dashboard").status_code == 404  # ancien dashboard supprimé (lot 7.1)
    other = Settings(
        mode=RunMode.ADDON, data_dir=tmp_path / "other", static_dir=static, home_assistant=None
    )
    with TestClient(create_app(other), client=("172.30.33.5", 50000)) as client:
        assert client.get("/").status_code == 403
