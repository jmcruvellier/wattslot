"""Accès minimal à l'API de Home Assistant (REST et WebSocket) pour les outils de développement."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from websockets.sync.client import connect


def ha_url() -> str:
    return os.environ.get("HA_URL", "http://localhost:8123").rstrip("/")


def token_file() -> Path:
    return Path(os.environ.get("HA_TOKEN_FILE", "ha_token"))


def read_token() -> str:
    return token_file().read_text(encoding="utf-8").strip()


def request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    timeout: float = 30,
) -> Any:
    """Requête REST ; renvoie le JSON décodé (ou None si la réponse est vide)."""
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(ha_url() + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else None


def wait_until_up(timeout_s: float = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            request("GET", "/api/onboarding")
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


class WebSocketSession:
    """Session WebSocket authentifiée, commandes envoyées une par une."""

    def __init__(self, token: str) -> None:
        url = ha_url().replace("http", "ws", 1) + "/api/websocket"
        self._ws = connect(url, max_size=None)
        self._next_id = 1
        if json.loads(self._ws.recv())["type"] != "auth_required":
            raise RuntimeError("authentification WebSocket inattendue")
        self._ws.send(json.dumps({"type": "auth", "access_token": token}))
        reply = json.loads(self._ws.recv())
        if reply["type"] != "auth_ok":
            raise RuntimeError(f"authentification WebSocket refusée : {reply}")

    def command(self, command: str, **params: Any) -> Any:
        message_id = self._next_id
        self._next_id += 1
        self._ws.send(json.dumps({"id": message_id, "type": command, **params}))
        while True:
            reply = json.loads(self._ws.recv())
            if reply.get("id") != message_id:
                continue
            if not reply.get("success"):
                raise RuntimeError(f"{command} : {reply.get('error')}")
            return reply.get("result")

    def close(self) -> None:
        self._ws.close()

    def __enter__(self) -> "WebSocketSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
