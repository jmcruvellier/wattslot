"""Branchement de l'Assist de Home Assistant (lots 6.2 et 6.3) : prompt système conseillé, dans
les six langues, à coller dans l'agent de conversation qui utilise le serveur MCP de
l'application (court, budget vérifié par les tests, il cite les outils par leur nom) ; adresse
du serveur MCP à donner à HA.

Le serveur MCP n'est appelé que sur le réseau local (par HA, par Open WebUI) : son adresse est
l'adresse interne de l'application. En extension, le serveur la connaît ; en mode autonome, la
page la retient la première fois qu'elle est ouverte depuis le réseau local (``app_settings``),
et l'affiche ensuite même depuis l'extérieur. Elle se corrige à la main.
"""

import socket
import sqlite3
from functools import cache
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from wattslot.languages import Language, language_of
from wattslot.runtime import RunMode

PROMPTS = Path(__file__).parent / "prompts"
PORT = 8100  # celui de l'image (Dockerfile) et de l'ingress de l'extension (config.yaml)

router = APIRouter()


@cache
def prompt(lang: str) -> str:
    """Prompt conseillé dans une langue des six (le français pour une langue inconnue)."""
    return (PROMPTS / f"{language_of(lang)}.txt").read_text(encoding="utf-8").strip()


class AssistantPrompt(BaseModel):
    language: Language
    prompt: str


@router.get("/api/assistant/prompt")
def get_prompt(lang: str = "fr") -> AssistantPrompt:
    """Prompt système conseillé pour l'agent de conversation de HA (page « Assistant »)."""
    return AssistantPrompt(language=language_of(lang), prompt=prompt(lang))


class AssistantConnection(BaseModel):
    mode: RunMode
    # Adresse retenue (``saved``) ; sinon, en extension, celle du réseau interne de HA (nom
    # d'hôte du conteneur, que le Supervisor dérive du dépôt et du slug) ; sinon aucune : la
    # page la retient depuis le réseau local.
    mcp_url: str | None = None
    saved: bool = False


class McpAddress(BaseModel):
    mcp_url: str | None  # aucune : revenir à l'adresse trouvée par l'application


SETTINGS_KEY = "assistant.mcp_url"


def connection(
    mode: RunMode, hostname: str | None = None, saved: str | None = None
) -> AssistantConnection:
    if saved:
        return AssistantConnection(mode=mode, mcp_url=saved, saved=True)
    if mode is not RunMode.ADDON:
        return AssistantConnection(mode=mode)
    return AssistantConnection(
        mode=mode, mcp_url=f"http://{hostname or socket.gethostname()}:{PORT}/mcp"
    )


def load_address(database: sqlite3.Connection) -> str | None:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (SETTINGS_KEY,)
    ).fetchone()
    return str(row[0]) if row else None


def save_address(database: sqlite3.Connection, url: str | None) -> None:
    """Retient l'adresse du serveur MCP (``None`` : l'oublie) ; ``ValueError`` si ce n'est pas
    une adresse http(s)."""
    with database:
        if url is None:
            database.execute("DELETE FROM app_settings WHERE key = ?", (SETTINGS_KEY,))
            return
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("invalid_url")
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, url.strip()),
        )
