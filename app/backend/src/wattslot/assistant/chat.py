"""Discussion avec l'assistant de Home Assistant depuis la page Assistant : chaque message est
transmis à un agent de conversation de HA (commande ``conversation/process``), dans la langue
de l'interface. L'identifiant de conversation rendu par HA revient avec le message suivant, pour
que l'agent garde le fil ; l'application n'enregistre pas la conversation. Un agent
« open_webui:<modèle> » part vers Open WebUI (``open_webui``), avec l'historique de la page.
"""

from typing import Any

from pydantic import BaseModel, Field

from wattslot.assistant.open_webui import HistoryLine
from wattslot.home_assistant import HomeAssistantClient
from wattslot.languages import Language


class ChatMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    agent_id: str | None = None  # aucun : l'agent de l'assistant préféré de HA
    conversation_id: str | None = None
    language: Language = "fr"
    # Messages précédents, pour Open WebUI qui ne garde pas le fil (HA s'en passe).
    history: list[HistoryLine] = Field(default=[], max_length=60)


class ChatReply(BaseModel):
    text: str
    conversation_id: str | None = None
    error: bool = False  # réponse d'erreur de l'agent (« response_type » à « error »)


def reply_of(result: Any) -> ChatReply:
    """Réponse de ``conversation/process`` : le texte à afficher et l'identifiant à renvoyer."""
    result = result or {}
    response = result.get("response") or {}
    speech = ((response.get("speech") or {}).get("plain") or {}).get("speech") or ""
    return ChatReply(
        text=str(speech),
        conversation_id=result.get("conversation_id"),
        error=response.get("response_type") == "error",
    )


async def send(client: HomeAssistantClient, message: ChatMessage) -> ChatReply:
    params: dict[str, Any] = {"text": message.text, "language": message.language}
    if message.agent_id:
        params["agent_id"] = message.agent_id
    if message.conversation_id:
        params["conversation_id"] = message.conversation_id
    return reply_of(await client.command("conversation/process", **params))
