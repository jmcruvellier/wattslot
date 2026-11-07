"""Open WebUI en appel direct (page Assistant)."""

import asyncio
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
    MAX_TOOL_ROUNDS,
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
        self.authorizations: list[str] = []  # en-tête Authorization de chaque requête
        # Outil que le modèle appelle d'abord quand des outils lui sont proposés.
        self.tool_call: dict[str, Any] | None = None
        self.endless = False  # appelle l'outil à chaque tour où des outils sont proposés
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
                fake.authorizations.append(self.headers.get("Authorization", ""))
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
                answered = [m for m in body["messages"] if m["role"] == "tool"]
                if fake.tool_call and "tools" in body and (fake.endless or not answered):
                    calls = [{"id": "appel-1", "type": "function", "function": fake.tool_call}]
                    answer = {"message": {"role": "assistant", "content": "", "tool_calls": calls}}
                elif answered:
                    content = f"Outil lu : {answered[-1]['content'][:20]}"
                    answer = {"message": {"role": "assistant", "content": content}}
                else:
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
    reply = asyncio.run(
        complete(
            OpenWebUISetting(url=fake.url, api_key=KEY),
            "qwen2.5:14b",
            "Prompt",
            history,
            "Et demain ?",
        )
    )

    assert reply == "Vu : qwen2.5:14b"
    sent = fake.received[0]
    assert sent["stream"] is False and "tools" not in sent
    assert sent["messages"] == [
        {"role": "system", "content": "Prompt"},
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Bonjour !"},
        {"role": "user", "content": "Et demain ?"},
    ]


def test_the_tools_called_by_the_model_run_here(fake: FakeOpenWebUI) -> None:
    """Par l'API, Open WebUI n'ajoute pas les outils du modèle : WattSlot les envoie, exécute
    les appels du modèle (arguments en JSON) et lui rend les résultats."""
    fake.tool_call = {"name": "get_day_plan", "arguments": '{"day": "today"}'}
    seen: list[tuple[str, dict[str, Any]]] = []

    async def call(name: str, arguments: dict[str, Any]) -> str:
        seen.append((name, arguments))
        return '{"cost": "1,84 €"}'

    tools = [{"type": "function", "function": {"name": "get_day_plan", "parameters": {}}}]
    setting = OpenWebUISetting(url=fake.url, api_key=KEY)
    reply = asyncio.run(complete(setting, "qwen3", "Prompt", [], "Coût ?", tools, call))

    assert seen == [("get_day_plan", {"day": "today"})]
    assert reply == 'Outil lu : {"cost": "1,84 €"}'
    first, second = fake.received
    assert first["tools"] == tools
    tool_line = second["messages"][-1]
    assert tool_line == {"role": "tool", "tool_call_id": "appel-1", "content": '{"cost": "1,84 €"}'}
    assert second["messages"][-2]["tool_calls"][0]["function"]["name"] == "get_day_plan"


def test_the_last_round_offers_no_tool(fake: FakeOpenWebUI) -> None:
    """Un modèle qui appellerait des outils sans fin : au dernier tour, plus d'outils proposés,
    il répond avec ce qu'il a lu."""
    fake.tool_call = {"name": "get_home", "arguments": {}}
    fake.endless = True
    calls = 0

    async def call(name: str, arguments: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "{}"

    tools = [{"type": "function", "function": {"name": "get_home", "parameters": {}}}]
    setting = OpenWebUISetting(url=fake.url, api_key=KEY)
    reply = asyncio.run(complete(setting, "qwen3", "Prompt", [], "Maison ?", tools, call))

    assert reply == "Outil lu : {}"
    assert calls == MAX_TOOL_ROUNDS == len(fake.received) - 1
    assert "tools" not in fake.received[-1] and "tools" in fake.received[-2]


def test_the_key_is_kept_replaced_or_cleared() -> None:
    saved = OpenWebUISetting(url="http://192.0.2.10:3000", api_key="ancienne")

    kept = merged(saved, OpenWebUIChange(url="http://192.0.2.10:3000/"))
    replaced = merged(saved, OpenWebUIChange(url="http://192.0.2.10:3000", api_key="nouvelle"))
    cleared = merged(saved, OpenWebUIChange(url="http://192.0.2.10:3000", clear_key=True))

    assert kept == OpenWebUISetting(url="http://192.0.2.10:3000", api_key="ancienne")
    assert replaced.api_key == "nouvelle"
    assert cleared.api_key is None


@pytest.mark.parametrize(
    "url",
    [
        "http://192.0.2.66:3000",  # autre hôte
        "http://192.0.2.10:3001",  # autre port
        "https://192.0.2.10:3000",  # autre schéma
        "http://192.0.2.10:3000@192.0.2.66",  # hôte réel après « @ »
        None,  # adresse effacée
    ],
)
def test_the_key_does_not_follow_the_address_to_another_server(url: str | None) -> None:
    """Changer l'adresse sans saisir de clé : la clé enregistrée n'est pas envoyée au nouveau
    serveur (test) ni gardée pour lui (enregistrement)."""
    saved = OpenWebUISetting(url="http://192.0.2.10:3000", api_key="ancienne")

    assert merged(saved, OpenWebUIChange(url=url)).api_key is None
    assert merged(saved, OpenWebUIChange(url=url, api_key="nouvelle")).api_key == "nouvelle"


def test_the_key_stays_on_the_same_server() -> None:
    """Même serveur : chemin, casse de l'hôte ou port par défaut écrit en plus."""
    saved = OpenWebUISetting(url="http://openwebui.local", api_key="ancienne")

    for url in (
        "http://openwebui.local/ui",
        "http://OpenWebUI.local:80",
        "http://openwebui.local/",
    ):
        assert merged(saved, OpenWebUIChange(url=url)).api_key == "ancienne"


def test_testing_another_address_does_not_send_the_saved_key(
    tmp_path: Path, fake: FakeOpenWebUI
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        api.put("/api/assistant/open-webui", json={"url": "http://192.0.2.10:3000", "api_key": KEY})

        tested = api.post("/api/assistant/open-webui/test", json={"url": fake.url})
        moved = api.put("/api/assistant/open-webui", json={"url": fake.url})

    assert tested.status_code == 502  # sans clé : rien n'est envoyé
    assert fake.authorizations == []  # le nouveau serveur ne reçoit rien
    assert moved.json() == {"url": fake.url, "has_key": False}


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
        # Les outils de WattSlot partent avec la question, et l'application les exécute.
        names = {t["function"]["name"] for t in fake.received[-1]["tools"]}
        assert {"get_day_plan", "get_home", "request_device"} <= names
        fake.tool_call = {"name": "get_home", "arguments": "{}"}
        reply = api.post(
            "/api/assistant/chat",
            json={"text": "Ma maison ?", "agent_id": "open_webui:qwen2.5:14b"},
        ).json()
        assert reply["text"].startswith("Outil lu : {")  # résultat JSON de get_home
        fake.tool_call = {"name": "outil_inconnu", "arguments": "{}"}
        reply = api.post(
            "/api/assistant/chat",
            json={"text": "Et ça ?", "agent_id": "open_webui:qwen2.5:14b"},
        ).json()
        assert reply["text"].startswith('Outil lu : {"error": "tool_f')  # rendu au modèle
        fake.tool_call = None

        wrong = api.post("/api/assistant/open-webui/test", json={"url": fake.url, "api_key": "x"})
        assert wrong.status_code == 502 and "x" not in wrong.json()["detail"].split()
        invalid = api.put("/api/assistant/open-webui", json={"url": "ftp://192.0.2.10"})
        assert invalid.status_code == 422
