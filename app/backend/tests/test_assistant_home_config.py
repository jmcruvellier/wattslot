"""Configuration de l'assistant vocal dans Home Assistant (sous-page des Réglages)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.fake_home_assistant import default_responses, fake_home_assistant, running_client
from tests.test_health import _settings
from wattslot.assistant.home_config import (
    AssistantChange,
    AssistantHomeConfig,
    UnknownChoiceError,
    change,
    home_config,
)
from wattslot.main import create_app

PIPELINES = {
    "pipelines": [
        {
            "id": "p1",
            "name": "Home Assistant",
            "language": "fr",
            "conversation_engine": "conversation.home_assistant",
            "conversation_language": "fr",
            "stt_engine": None,
            "stt_language": None,
            "tts_engine": None,
            "tts_language": None,
            "tts_voice": None,
            "wake_word_entity": None,
            "wake_word_id": None,
            "prefer_local_intents": False,
        },
        {"id": "p2", "name": "Avec LLM", "conversation_engine": "conversation.llm"},
    ],
    "preferred_pipeline": "p1",
}
AGENTS = {
    "agents": [
        {"id": "conversation.home_assistant", "name": "Home Assistant"},
        {"id": "conversation.llm", "name": "Modèle de langue"},
    ]
}
MCP_ENTRIES = [{"entry_id": "e1", "domain": "mcp", "title": "WattSlot", "state": "loaded"}]


def _responses(sent: list[dict[str, Any]]) -> dict[str, Any]:
    def record(message: dict[str, Any]) -> Any:
        sent.append(message)
        return {}

    return default_responses() | {
        "assist_pipeline/pipeline/list": PIPELINES,
        "conversation/agent/list": AGENTS,
        "config_entries/get": lambda message: MCP_ENTRIES if message["domain"] == "mcp" else [],
        "assist_pipeline/pipeline/update": record,
        "assist_pipeline/pipeline/set_preferred": record,
    }


async def _read(responses: dict[str, Any]) -> AssistantHomeConfig:
    async with running_client(fake_home_assistant(responses)) as client:
        return await home_config(client)


async def _change(wanted: AssistantChange) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    async with running_client(fake_home_assistant(_responses(sent))) as client:
        await change(client, wanted)
    return sent


def test_the_configuration_is_read_from_home_assistant() -> None:
    found = asyncio.run(_read(_responses([])))

    assert found.connected
    assert [(m.title, m.state) for m in found.mcp] == [("WattSlot", "loaded")]
    assert [(p.id, p.conversation_engine) for p in found.pipelines] == [
        ("p1", "conversation.home_assistant"),
        ("p2", "conversation.llm"),
    ]
    assert found.preferred_pipeline == "p1"
    assert [a.id for a in found.agents] == ["conversation.home_assistant", "conversation.llm"]


def test_a_missing_part_leaves_the_others() -> None:
    # Sans l'intégration MCP ni Assist (commandes en erreur), les agents restent.
    found = asyncio.run(_read(default_responses() | {"conversation/agent/list": AGENTS}))

    assert found.connected
    assert found.mcp == [] and found.pipelines == [] and found.preferred_pipeline is None
    assert len(found.agents) == 2


def test_changing_the_agent_updates_the_whole_pipeline() -> None:
    sent = asyncio.run(
        _change(AssistantChange(pipeline_id="p1", conversation_engine="conversation.llm"))
    )

    assert [m["type"] for m in sent] == ["assist_pipeline/pipeline/update"]
    update = sent[0]
    assert update["pipeline_id"] == "p1"
    assert update["conversation_engine"] == "conversation.llm"
    assert update["name"] == "Home Assistant" and update["prefer_local_intents"] is False


def test_choosing_another_pipeline_makes_it_preferred() -> None:
    sent = asyncio.run(
        _change(AssistantChange(pipeline_id="p2", conversation_engine="conversation.llm"))
    )

    assert [(m["type"], m["pipeline_id"]) for m in sent] == [
        ("assist_pipeline/pipeline/set_preferred", "p2")
    ]


@pytest.mark.parametrize(
    "wanted",
    [
        AssistantChange(pipeline_id="inconnu", conversation_engine="conversation.llm"),
        AssistantChange(pipeline_id="p1", conversation_engine="conversation.inconnu"),
    ],
)
def test_an_unknown_choice_is_refused(wanted: AssistantChange) -> None:
    with pytest.raises(UnknownChoiceError):
        asyncio.run(_change(wanted))


def test_without_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        found = api.get("/api/assistant/home").json()
        refused = api.put(
            "/api/assistant/home", json={"pipeline_id": "p1", "conversation_engine": "x"}
        )

    assert found == {
        "connected": False,
        "mcp": [],
        "pipelines": [],
        "preferred_pipeline": None,
        "agents": [],
    }
    assert refused.status_code == 503
