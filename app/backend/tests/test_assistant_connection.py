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
    assert found == {"mode": "standalone", "mcp_url": None}


def test_in_addon_mode_home_assistant_joins_the_container_by_its_hostname(tmp_path: Path) -> None:
    found = connection(RunMode.ADDON, "a0d7b954-wattslot")
    assert found.mcp_url == "http://a0d7b954-wattslot:8100/mcp"
    settings = Settings(mode=RunMode.ADDON, data_dir=tmp_path, static_dir=None, home_assistant=None)
    with TestClient(create_app(settings), client=(SUPERVISOR_INGRESS_ADDRESS, 50000)) as api:
        url = api.get("/api/assistant/connection").json()["mcp_url"]
    assert url.startswith("http://") and url.endswith(":8100/mcp")
