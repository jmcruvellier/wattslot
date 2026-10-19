"""Open WebUI en appel direct (page Assistant) : discuter avec un de ses modèles sans passer par
Home Assistant, par son API compatible OpenAI (``/api/models``, ``/api/chat/completions``).

Adresse et clé d'API sont gardées dans ``app_settings`` ; la clé ne revient jamais à la page
(``has_key`` seulement), n'est écrite dans aucun journal ni message d'erreur, et n'entre pas
dans l'export de la maison. Open WebUI ne garde pas le fil par cette API : la page renvoie
l'historique avec chaque message, après le prompt conseillé en instructions système.
"""

import json
import sqlite3
import urllib.error
import urllib.request
from typing import Any, Literal

from pydantic import BaseModel, Field

from wattslot import __version__

SETTINGS_KEY = "open_webui"
AGENT_PREFIX = "open_webui:"  # agent du chat : « open_webui:<modèle> »
MODELS_TIMEOUT_S = 15
CHAT_TIMEOUT_S = 120


class OpenWebUISetting(BaseModel):
    url: str | None = None
    api_key: str | None = None

    @property
    def ready(self) -> bool:
        return bool(self.url and self.api_key)


class OpenWebUIState(BaseModel):
    """Ce que la page voit du réglage : l'adresse, et seulement s'il y a une clé."""

    url: str | None = None
    has_key: bool = False


class OpenWebUIChange(BaseModel):
    url: str | None = Field(default=None, max_length=500, pattern=r"^https?://\S+$")
    api_key: str | None = Field(default=None, max_length=500)  # aucune : garder l'actuelle
    clear_key: bool = False


class Model(BaseModel):
    id: str
    name: str


class HistoryLine(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class OpenWebUIError(Exception):
    """Open WebUI injoignable ou réponse refusée (le message ne contient jamais la clé)."""


def load(database: sqlite3.Connection) -> OpenWebUISetting:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (SETTINGS_KEY,)
    ).fetchone()
    return OpenWebUISetting.model_validate(json.loads(row[0])) if row else OpenWebUISetting()


def state(setting: OpenWebUISetting) -> OpenWebUIState:
    return OpenWebUIState(url=setting.url, has_key=bool(setting.api_key))


def merged(saved: OpenWebUISetting, change: OpenWebUIChange) -> OpenWebUISetting:
    """Réglage après la modification : la clé saisie, sinon l'actuelle, sauf si effacée."""
    key = None if change.clear_key else (change.api_key or saved.api_key)
    url = change.url.rstrip("/") if change.url else None
    return OpenWebUISetting(url=url, api_key=key)


def save(database: sqlite3.Connection, setting: OpenWebUISetting) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, setting.model_dump_json()),
        )


def _request(setting: OpenWebUISetting, path: str, body: object | None, timeout: float) -> Any:
    if not setting.ready:
        raise OpenWebUIError("Open WebUI non configuré")
    request = urllib.request.Request(
        f"{setting.url}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {setting.api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"wattslot/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise OpenWebUIError(f"HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise OpenWebUIError(str(reason)) from None
    except ValueError:
        raise OpenWebUIError("réponse illisible") from None


def models(setting: OpenWebUISetting) -> list[Model]:
    """Modèles proposés par Open WebUI (``{"data": [{"id", "name"}]}``), par nom."""
    found = _request(setting, "/api/models", None, MODELS_TIMEOUT_S) or {}
    listed = found.get("data") if isinstance(found, dict) else found
    return sorted(
        (
            Model(id=str(m["id"]), name=str(m.get("name") or m["id"]))
            for m in listed or []
            if isinstance(m, dict) and m.get("id")
        ),
        key=lambda m: m.name.lower(),
    )


def complete(
    setting: OpenWebUISetting,
    model: str,
    system: str,
    history: list[HistoryLine],
    text: str,
) -> str:
    """Réponse du modèle au message ``text``, après les instructions et l'historique."""
    messages = [{"role": "system", "content": system}]
    messages += [line.model_dump() for line in history]
    messages.append({"role": "user", "content": text})
    found = _request(
        setting,
        "/api/chat/completions",
        {"model": model, "messages": messages, "stream": False},
        CHAT_TIMEOUT_S,
    )
    try:
        return str(found["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        raise OpenWebUIError("réponse sans message") from None
