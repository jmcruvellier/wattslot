"""Adresse du serveur MCP à donner à Home Assistant (lot 6.3)."""

from pathlib import Path

from fastapi.testclient import TestClient

from wattslot.assistant.prompts import connection
from wattslot.ingress import SUPERVISOR_INGRESS_ADDRESS
from wattslot.main import create_app
from wattslot.runtime import RunMode, Settings


def test_in_standalone_mode_the_page_uses_the_browser_address(tmp_path: Path) -> None:
    settings = Settings(
        mode=RunMode.STANDALONE, data_dir=tmp_path, static_dir=None, home_assistant=None
    )
    with TestClient(create_app(settings)) as api:
        found = api.get("/api/assistant/connection").json()
    assert found == {"mode": "standalone", "mcp_url": None, "saved": False}


def test_the_internal_address_is_kept_and_can_be_corrected(tmp_path: Path) -> None:
    """En mode autonome, la page retient l'adresse interne ; elle se corrige ou s'oublie."""
    settings = Settings(
        mode=RunMode.STANDALONE, data_dir=tmp_path, static_dir=None, home_assistant=None
    )
    with TestClient(create_app(settings)) as api:
        saved = api.put("/api/assistant/connection", json={"mcp_url": "http://192.0.2.10:8100/mcp"})
        assert saved.json() == {
            "mode": "standalone",
            "mcp_url": "http://192.0.2.10:8100/mcp",
            "saved": True,
        }
        assert (
            api.get("/api/assistant/connection").json()["mcp_url"] == "http://192.0.2.10:8100/mcp"
        )
        refused = api.put("/api/assistant/connection", json={"mcp_url": "192.0.2.10:8100"})
        assert (refused.status_code, refused.json()["detail"]) == (422, "invalid_url")
        forgotten = api.put("/api/assistant/connection", json={"mcp_url": None}).json()
    assert forgotten == {"mode": "standalone", "mcp_url": None, "saved": False}


def test_in_addon_mode_home_assistant_joins_the_container_by_its_hostname(tmp_path: Path) -> None:
    found = connection(RunMode.ADDON, "a0d7b954-wattslot")
    assert found.mcp_url == "http://a0d7b954-wattslot:8100/mcp"
    settings = Settings(mode=RunMode.ADDON, data_dir=tmp_path, static_dir=None, home_assistant=None)
    with TestClient(create_app(settings), client=(SUPERVISOR_INGRESS_ADDRESS, 50000)) as api:
        url = api.get("/api/assistant/connection").json()["mcp_url"]
    assert url.startswith("http://") and url.endswith(":8100/mcp")
