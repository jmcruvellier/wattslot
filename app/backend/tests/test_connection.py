"""Connexion à HA en mode autonome (lot 4.6) : OAuth2 de HA, jeton saisi, jetons rafraîchis."""

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.fake_home_assistant import TOKEN, fake_home_assistant, running_client
from tests.test_health import _settings
from wattslot import connection
from wattslot.connection import ConnectionFailed, StoredConnection, TokenProvider
from wattslot.home_assistant import ConnectionState
from wattslot.main import create_app
from wattslot.runtime import RunMode, load_settings

HA = "http://homeassistant.local:8123"
APP = "http://192.0.2.10:8100"


class FakeHA:
    """``/auth/token`` et ``/api/`` de HA."""

    def __init__(self) -> None:
        self.forms: list[tuple[str, dict[str, str]]] = []
        self.refused = False

    async def post(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        self.forms.append((url, form))
        if self.refused:
            raise ConnectionFailed("HTTP 400")
        if form.get("action") == "revoke":
            return {}
        return {
            "access_token": f"access-{len(self.forms)}",
            "refresh_token": "refresh" if form["grant_type"] == "authorization_code" else None,
            "expires_in": 1800,
        }

    async def get(self, url: str, token: str) -> int:
        return 200 if token == "good" else 401


def test_the_file_keeps_the_connection(tmp_path: Path) -> None:
    stored = StoredConnection(url=HA, method="token", token="secret")
    connection.save(tmp_path, stored)

    assert connection.load(tmp_path) == stored
    if os.name == "posix":
        assert (connection.path_in(tmp_path).stat().st_mode & 0o777) == 0o600
    connection.delete(tmp_path)
    assert connection.load(tmp_path) is None


def test_code_exchange_and_token_refresh(tmp_path: Path) -> None:
    ha = FakeHA()
    stored = asyncio.run(connection.exchange_code(HA, "code", APP, ha.post))
    assert (stored.access_token, stored.refresh_token) == ("access-1", "refresh")
    assert ha.forms[0] == (
        f"{HA}/auth/token",
        {"grant_type": "authorization_code", "code": "code", "client_id": APP},
    )

    provider = TokenProvider(tmp_path, stored, ha.post)
    assert asyncio.run(provider()) == "access-1"  # encore valable : pas de rafraîchissement
    assert len(ha.forms) == 1

    soon = stored.model_copy(update={"expires_at": time.time() + 60})
    provider = TokenProvider(tmp_path, soon, ha.post)
    assert asyncio.run(provider()) == "access-2"
    assert ha.forms[1][1]["grant_type"] == "refresh_token"
    saved = connection.load(tmp_path)
    assert saved is not None and saved.access_token == "access-2"
    assert saved.refresh_token == "refresh"  # gardé : HA n'en renvoie pas de nouveau

    asyncio.run(connection.revoke(saved, ha.post))
    assert ha.forms[2][1] == {"token": "refresh", "action": "revoke"}


def test_login_requests_expire_and_are_single_use() -> None:
    logins = connection.PendingLogins()
    query = parse_qs(urlsplit(logins.start(HA, APP)).query)

    assert query["client_id"] == [APP]
    assert query["redirect_uri"] == [f"{APP}/auth/callback"]
    state = query["state"][0]
    assert logins.take(state) == (HA, APP)
    assert logins.take(state) is None


def test_environment_first_then_the_saved_connection(tmp_path: Path) -> None:
    connection.save(tmp_path, StoredConnection(url=HA, method="token", token="saved"))

    from_env = load_settings({"WATTSLOT_DATA_DIR": str(tmp_path), "HA_URL": HA, "HA_TOKEN": "env"})
    assert from_env.connection_source == "env" and from_env.home_assistant is not None
    assert from_env.home_assistant.token == "env"

    saved = load_settings({"WATTSLOT_DATA_DIR": str(tmp_path)})
    assert saved.connection_source == "saved" and saved.home_assistant is not None
    assert saved.home_assistant.websocket_url == "ws://homeassistant.local:8123/api/websocket"
    assert saved.home_assistant.token_provider is not None

    addon = load_settings({"WATTSLOT_DATA_DIR": str(tmp_path), "SUPERVISOR_TOKEN": "x"})
    assert addon.mode is RunMode.ADDON and addon.connection_source == "supervisor"


def test_the_client_asks_its_token_at_each_connection() -> None:
    asked: list[int] = []

    async def provider() -> str:
        asked.append(1)
        return TOKEN

    async def connect() -> ConnectionState:
        async with running_client(
            fake_home_assistant(), token="périmé", token_provider=provider
        ) as client:
            return client.status.state

    assert asyncio.run(connect()) is ConnectionState.CONNECTED and asked


@pytest.fixture
def ha(monkeypatch: pytest.MonkeyPatch) -> FakeHA:
    fake = FakeHA()
    monkeypatch.setattr(connection, "post_form", fake.post)
    monkeypatch.setattr(connection, "get_status", fake.get)
    return fake


def test_connect_with_a_token(tmp_path: Path, ha: FakeHA) -> None:
    restarts: list[int] = []
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as api:
        api.app.state.restart = lambda: restarts.append(1)  # type: ignore[attr-defined]
        assert api.get("/api/connection").json()["source"] is None

        refused = api.post("/api/connection/token", json={"url": HA, "token": "bad"})
        assert refused.status_code == 400 and refused.json()["detail"] == "token_refused"
        assert (
            api.post("/api/connection/token", json={"url": "ha", "token": "x"}).status_code == 422
        )
        assert restarts == []

        ok = api.post("/api/connection/token", json={"url": f"{HA}/", "token": "good"})
        assert ok.json() == {"restarting": True} and restarts == [1]

    saved = connection.load(settings.data_dir)
    assert saved is not None and (saved.url, saved.token) == (HA, "good")


def test_connect_with_home_assistant_then_disconnect(tmp_path: Path, ha: FakeHA) -> None:
    restarts: list[int] = []
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as api:
        api.app.state.restart = lambda: restarts.append(1)  # type: ignore[attr-defined]
        authorize = api.post("/api/connection/oauth", json={"url": HA, "client_id": APP}).json()
        state = parse_qs(urlsplit(authorize["authorize_url"]).query)["state"][0]

        expired = api.get(
            "/auth/callback", params={"state": "autre", "code": "c"}, follow_redirects=False
        )
        assert expired.headers["location"] == "../?connection=expired"

        back = api.get(
            "/auth/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
        assert back.status_code == 303 and back.headers["location"] == "../?connection=ok"
        saved = connection.load(settings.data_dir)
        assert saved is not None and saved.method == "oauth" and saved.refresh_token == "refresh"

        assert api.delete("/api/connection").json() == {"restarting": True}
        assert connection.load(settings.data_dir) is None
        assert ha.forms[-1][1]["action"] == "revoke" and restarts == [1, 1]


def test_the_address_of_ha_url_is_proposed_without_token(tmp_path: Path) -> None:
    settings = load_settings({"WATTSLOT_DATA_DIR": str(tmp_path), "HA_URL": HA})
    with TestClient(create_app(settings)) as api:
        info = api.get("/api/connection").json()

    assert info["source"] is None and info["url"] == HA


def test_a_connection_set_by_the_environment_cannot_be_changed(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path, connection_source="env"))) as api:
        changed = api.post("/api/connection/token", json={"url": HA, "token": "good"})
        assert changed.status_code == 409 and changed.json()["detail"] == "set_by_environment"
