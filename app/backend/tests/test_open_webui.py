"""Open WebUI en appel direct (page Assistant)."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot.assistant.open_webui import (
    HistoryLine,
    OpenWebUIChange,
    OpenWebUIError,
    OpenWebUISetting,
    complete,
    merged,
    models,
)
from wattslot.main import create_app

KEY = "cle-de-test"


class FakeOpenWebUI:
    """Faux Open WebUI : vérifie la clé, liste deux modèles, répond aux messages."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, body: object) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                if self.headers.get("Authorization") == f"Bearer {KEY}":
                    return True
                self._reply(401, {"detail": "Not authenticated"})
                return False

            def do_GET(self) -> None:
                if self._authorized() and self.path == "/api/models":
                    models = [{"id": "qwen2.5:14b", "name": "Qwen"}, {"id": "llama3.1:8b"}]
                    self._reply(200, {"data": models})

            def do_POST(self) -> None:
                if not self._authorized():
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.received.append(body)
                answer = {"message": {"role": "assistant", "content": f"Vu : {body['model']}"}}
                self._reply(200, {"choices": [answer]})

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"


@pytest.fixture
def fake() -> Iterator[FakeOpenWebUI]:
    server = FakeOpenWebUI()
    thread = threading.Thread(target=server.server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.server.shutdown()


def test_models_are_listed_by_name(fake: FakeOpenWebUI) -> None:
    found = models(OpenWebUISetting(url=fake.url, api_key=KEY))

    assert [(m.id, m.name) for m in found] == [
        ("llama3.1:8b", "llama3.1:8b"),
        ("qwen2.5:14b", "Qwen"),
    ]


def test_a_wrong_key_gives_the_status_without_the_key(fake: FakeOpenWebUI) -> None:
    with pytest.raises(OpenWebUIError) as error:
        models(OpenWebUISetting(url=fake.url, api_key="mauvaise"))

    assert str(error.value) == "HTTP 401"


def test_an_unreachable_address_is_an_error() -> None:
    with pytest.raises(OpenWebUIError):
        models(OpenWebUISetting(url="http://127.0.0.1:9", api_key=KEY))


def test_the_message_follows_the_instructions_and_the_history(fake: FakeOpenWebUI) -> None:
    history = [
        HistoryLine(role="user", content="Bonjour"),
        HistoryLine(role="assistant", content="Bonjour !"),
    ]
    reply = complete(
        OpenWebUISetting(url=fake.url, api_key=KEY), "qwen2.5:14b", "Prompt", history, "Et demain ?"
    )

    assert reply == "Vu : qwen2.5:14b"
    sent = fake.received[0]
    assert sent["stream"] is False
    assert sent["messages"] == [
        {"role": "system", "content": "Prompt"},
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Bonjour !"},
        {"role": "user", "content": "Et demain ?"},
    ]


def test_the_key_is_kept_replaced_or_cleared() -> None:
    saved = OpenWebUISetting(url="http://192.0.2.10:3000", api_key="ancienne")

    kept = merged(saved, OpenWebUIChange(url="http://192.0.2.10:3000/"))
    replaced = merged(saved, OpenWebUIChange(url="http://192.0.2.10:3000", api_key="nouvelle"))
    cleared = merged(saved, OpenWebUIChange(url="http://192.0.2.10:3000", clear_key=True))

    assert kept == OpenWebUISetting(url="http://192.0.2.10:3000", api_key="ancienne")
    assert replaced.api_key == "nouvelle"
    assert cleared.api_key is None


def test_the_api_never_returns_the_key(tmp_path: Path, fake: FakeOpenWebUI) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/assistant/open-webui").json() == {"url": None, "has_key": False}
        assert api.get("/api/assistant/open-webui/models").json() == []
        refused = api.post(
            "/api/assistant/chat", json={"text": "Bonjour", "agent_id": "open_webui:qwen2.5:14b"}
        )
        assert refused.status_code == 503

        tested = api.post("/api/assistant/open-webui/test", json={"url": fake.url, "api_key": KEY})
        assert [m["id"] for m in tested.json()] == ["llama3.1:8b", "qwen2.5:14b"]
        assert api.get("/api/assistant/open-webui").json()["has_key"] is False  # pas enregistré

        saved = api.put("/api/assistant/open-webui", json={"url": fake.url, "api_key": KEY})
        assert saved.json() == {"url": fake.url, "has_key": True}
        assert KEY not in saved.text
        assert len(api.get("/api/assistant/open-webui/models").json()) == 2

        reply = api.post(
            "/api/assistant/chat",
            json={
                "text": "Pourquoi 11 h ?",
                "agent_id": "open_webui:qwen2.5:14b",
                "language": "en",
                "history": [{"role": "user", "content": "Bonjour"}],
            },
        ).json()
        assert reply == {"text": "Vu : qwen2.5:14b", "conversation_id": None, "error": False}
        system = fake.received[-1]["messages"][0]
        assert system["role"] == "system" and system["content"]  # prompt conseillé, en anglais

        wrong = api.post("/api/assistant/open-webui/test", json={"url": fake.url, "api_key": "x"})
        assert wrong.status_code == 502 and "x" not in wrong.json()["detail"].split()
        invalid = api.put("/api/assistant/open-webui", json={"url": "ftp://192.0.2.10"})
        assert invalid.status_code == 422
