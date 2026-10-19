"""Configuration de l'assistant vocal dans Home Assistant (sous-page « Assistant vocal » des
Réglages) : l'intégration « Model Context Protocol » qui joint le serveur MCP de l'application,
les assistants (pipelines Assist) avec le préféré, et les agents de conversation possibles.

L'application ne garde aucun réglage de l'assistant : tout est lu dans HA à la demande, et une
modification change l'assistant préféré ou son agent de conversation dans HA. Sans HA connecté,
la configuration est vide (``connected`` faux).
"""

from typing import Any

from pydantic import BaseModel

from wattslot.home_assistant import ConnectionState, HomeAssistantClient

# Champs d'un assistant que la commande ``assist_pipeline/pipeline/update`` attend tous.
_PIPELINE_FIELDS = (
    "name",
    "language",
    "conversation_engine",
    "conversation_language",
    "stt_engine",
    "stt_language",
    "tts_engine",
    "tts_language",
    "tts_voice",
    "wake_word_entity",
    "wake_word_id",
    "prefer_local_intents",
)


class McpIntegration(BaseModel):
    title: str
    state: str  # état de l'entrée de configuration : « loaded », « setup_error »…


class Pipeline(BaseModel):
    id: str
    name: str
    conversation_engine: str | None = None


class Agent(BaseModel):
    id: str
    name: str


class AssistantHomeConfig(BaseModel):
    connected: bool
    mcp: list[McpIntegration] = []  # vide : intégration non installée
    pipelines: list[Pipeline] = []
    preferred_pipeline: str | None = None
    agents: list[Agent] = []


class AssistantChange(BaseModel):
    pipeline_id: str
    conversation_engine: str


class UnknownChoiceError(ValueError):
    """Assistant ou agent de conversation que HA ne connaît pas."""


def _connected(client: HomeAssistantClient | None) -> bool:
    return client is not None and client.status.state is ConnectionState.CONNECTED


async def _optional(client: HomeAssistantClient, command: str, **params: Any) -> Any:
    try:
        return await client.command(command, **params)
    except Exception:  # noqa: BLE001 — une partie absente laisse le reste de la page
        return None


async def _pipelines(client: HomeAssistantClient) -> tuple[list[dict[str, Any]], str | None]:
    found = await _optional(client, "assist_pipeline/pipeline/list") or {}
    return list(found.get("pipelines") or []), found.get("preferred_pipeline")


async def home_config(client: HomeAssistantClient | None) -> AssistantHomeConfig:
    if client is None or not _connected(client):
        return AssistantHomeConfig(connected=False)
    entries = await _optional(client, "config_entries/get", domain="mcp") or []
    pipelines, preferred = await _pipelines(client)
    agents = (await _optional(client, "conversation/agent/list") or {}).get("agents") or []
    return AssistantHomeConfig(
        connected=True,
        mcp=[
            McpIntegration(title=str(entry.get("title") or "mcp"), state=str(entry.get("state")))
            for entry in entries
            if entry.get("domain", "mcp") == "mcp"
        ],
        pipelines=[
            Pipeline(
                id=str(p["id"]),
                name=str(p.get("name") or p["id"]),
                conversation_engine=p.get("conversation_engine"),
            )
            for p in pipelines
            if p.get("id")
        ],
        preferred_pipeline=preferred,
        agents=[
            Agent(id=str(a["id"]), name=str(a.get("name") or a["id"]))
            for a in agents
            if a.get("id")
        ],
    )


async def change(client: HomeAssistantClient, wanted: AssistantChange) -> None:
    """Rend l'assistant ``pipeline_id`` préféré et lui donne l'agent ``conversation_engine`` ;
    ``UnknownChoiceError`` si HA ne connaît pas l'un des deux."""
    pipelines, preferred = await _pipelines(client)
    pipeline = next((p for p in pipelines if p.get("id") == wanted.pipeline_id), None)
    agents = (await client.command("conversation/agent/list") or {}).get("agents") or []
    if pipeline is None or not any(a.get("id") == wanted.conversation_engine for a in agents):
        raise UnknownChoiceError(wanted.pipeline_id, wanted.conversation_engine)
    if pipeline.get("conversation_engine") != wanted.conversation_engine:
        fields = {key: pipeline.get(key) for key in _PIPELINE_FIELDS if key in pipeline}
        fields["conversation_engine"] = wanted.conversation_engine
        await client.command(
            "assist_pipeline/pipeline/update", pipeline_id=wanted.pipeline_id, **fields
        )
    if preferred != wanted.pipeline_id:
        await client.command(
            "assist_pipeline/pipeline/set_preferred", pipeline_id=wanted.pipeline_id
        )
