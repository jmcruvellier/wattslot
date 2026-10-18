"""Connexion à Home Assistant en mode autonome (lot 4.6, point
n° 3) : « Se connecter avec Home Assistant » (OAuth2 de HA), repli sur un jeton longue durée.

HA identifie une application par son adresse (``client_id``), sans enregistrement préalable ; le
retour (``redirect_uri``) se fait à la même adresse. Le code reçu est échangé côté serveur contre
un jeton d'accès (30 minutes) et un jeton de rafraîchissement. La connexion est gardée dans un
fichier à part, ``/data/home_assistant.json`` (droits 600) : jamais dans la base, l'export ni le
rapport, jamais renvoyée par l'API. Les variables d'environnement gardent la priorité.
"""

import asyncio
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

FILENAME = "home_assistant.json"
STATE_SECONDS = 600  # validité d'une demande de connexion OAuth2
REFRESH_MARGIN_S = 300  # jeton d'accès rafraîchi s'il expire dans moins de 5 minutes

Post = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]
Get = Callable[[str, str], Awaitable[int]]


class ConnectionFailed(Exception):
    """HA a refusé (jeton, code) ou n'a pas répondu."""


class StoredConnection(BaseModel):
    url: str  # adresse de HA, telle qu'on l'ouvre dans un navigateur
    method: Literal["oauth", "token"]
    token: str | None = None  # jeton longue durée (méthode « token »)
    client_id: str | None = None  # adresse de l'application (méthode « oauth »)
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: float | None = None  # horodatage Unix


def normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("invalid_url")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


# --- Fichier ------------------------------------------------------------------------------


def path_in(data_dir: Path) -> Path:
    return data_dir / FILENAME


def load(data_dir: Path) -> StoredConnection | None:
    path = path_in(data_dir)
    if not path.is_file():
        return None
    try:
        return StoredConnection.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save(data_dir: Path, connection: StoredConnection) -> None:
    """Écrit le fichier avec les droits 600, par un fichier temporaire (jamais à moitié écrit)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = path_in(data_dir)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(connection.model_dump_json())
    os.replace(temporary, path)


def delete(data_dir: Path) -> None:
    path_in(data_dir).unlink(missing_ok=True)


# --- Échanges avec HA ---------------------------------------------------------------------


async def post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    def send() -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise ConnectionFailed(f"HTTP {exc.code}") from exc
        except OSError as exc:
            raise ConnectionFailed(str(exc)) from exc
        return dict(json.loads(body)) if body else {}

    return await asyncio.to_thread(send)


async def get_status(url: str, token: str) -> int:
    def send() -> int:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except OSError as exc:
            raise ConnectionFailed(str(exc)) from exc

    return await asyncio.to_thread(send)


async def check_token(url: str, token: str, get: Get = get_status) -> None:
    """Vérifie un jeton auprès de HA (``GET /api/``) ; ``ConnectionFailed`` sinon."""
    status = await get(f"{url}/api/", token)
    if status != 200:
        raise ConnectionFailed(f"HTTP {status}")


def _with_tokens(connection: StoredConnection, answer: dict[str, Any]) -> StoredConnection:
    if not answer.get("access_token"):
        raise ConnectionFailed("réponse sans jeton")
    return connection.model_copy(
        update={
            "access_token": str(answer["access_token"]),
            "refresh_token": str(answer.get("refresh_token") or connection.refresh_token or ""),
            "expires_at": time.time() + float(answer.get("expires_in") or 1800),
        }
    )


async def exchange_code(
    url: str, code: str, client_id: str, post: Post = post_form
) -> StoredConnection:
    answer = await post(
        f"{url}/auth/token",
        {"grant_type": "authorization_code", "code": code, "client_id": client_id},
    )
    return _with_tokens(StoredConnection(url=url, method="oauth", client_id=client_id), answer)


async def refresh(connection: StoredConnection, post: Post = post_form) -> StoredConnection:
    answer = await post(
        f"{connection.url}/auth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": connection.refresh_token or "",
            "client_id": connection.client_id or "",
        },
    )
    return _with_tokens(connection, answer)


async def revoke(connection: StoredConnection, post: Post = post_form) -> None:
    """Révoque le jeton de rafraîchissement auprès de HA (sans effet sur un jeton longue durée,
    à supprimer dans le profil de HA)."""
    if connection.method == "oauth" and connection.refresh_token:
        await post(
            f"{connection.url}/auth/token", {"token": connection.refresh_token, "action": "revoke"}
        )


class TokenProvider:
    """Jeton à présenter à HA à chaque (re)connexion : le jeton longue durée, ou le jeton d'accès
    OAuth2, rafraîchi et réenregistré s'il expire bientôt."""

    def __init__(
        self, data_dir: Path, connection: StoredConnection, post: Post = post_form
    ) -> None:
        self._data_dir = data_dir
        self._connection = connection
        self._post = post
        self._lock = asyncio.Lock()

    async def __call__(self) -> str:
        current = self._connection
        if current.method == "token":
            return current.token or ""
        async with self._lock:
            current = self._connection
            if current.expires_at is None or current.expires_at - time.time() < REFRESH_MARGIN_S:
                current = await refresh(current, self._post)
                save(self._data_dir, current)
                self._connection = current
            return current.access_token or ""


# --- Demandes de connexion OAuth2 ---------------------------------------------------------


class PendingLogins:
    """Demandes de connexion en cours (``state`` → adresse de HA et de l'application)."""

    def __init__(self) -> None:
        self._pending: dict[str, tuple[str, str, float]] = {}

    def start(self, url: str, client_id: str) -> str:
        """Adresse de la page de connexion de HA."""
        now = time.time()
        self._pending = {k: v for k, v in self._pending.items() if now - v[2] < STATE_SECONDS}
        state = secrets.token_urlsafe(24)
        self._pending[state] = (url, client_id, now)
        query = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri(client_id),
                "state": state,
                "response_type": "code",
            }
        )
        return f"{url}/auth/authorize?{query}"

    def take(self, state: str) -> tuple[str, str] | None:
        found = self._pending.pop(state, None)
        if found is None or time.time() - found[2] >= STATE_SECONDS:
            return None
        return found[0], found[1]


def redirect_uri(client_id: str) -> str:
    """Retour de HA : ``auth/callback`` sous l'adresse de l'application."""
    return client_id.rstrip("/") + "/auth/callback"
