"""Branchement de l'Assist de Home Assistant (lots 6.2 et 6.3) : prompt système conseillé, dans
les six langues, à coller dans l'agent de conversation qui utilise le serveur MCP de
l'application (court, budget vérifié par les tests, il cite les outils par leur nom) ; adresse
du serveur MCP à donner à HA.
"""

import socket
from functools import cache
from pathlib import Path

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
    # En extension : adresse sur le réseau interne de HA (nom d'hôte du conteneur, que le
    # Supervisor dérive du dépôt et du slug). En mode autonome : aucune, celle du navigateur.
    mcp_url: str | None = None


def connection(mode: RunMode, hostname: str | None = None) -> AssistantConnection:
    if mode is not RunMode.ADDON:
        return AssistantConnection(mode=mode)
    return AssistantConnection(
        mode=mode, mcp_url=f"http://{hostname or socket.gethostname()}:{PORT}/mcp"
    )
