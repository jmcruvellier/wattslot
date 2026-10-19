"""Discussion avec l'assistant de Home Assistant depuis la page Assistant."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.fake_home_assistant import default_responses, fake_home_assistant, running_client
from tests.test_health import _settings
from wattslot.assistant.chat import ChatMessage, ChatReply, reply_of, send
from wattslot.home_assistant import CommandError
from wattslot.main import create_app


def _answer(text: str, kind: str = "action_done") -> dict[str, Any]:
    return {
        "response": {
            "response_type": kind,
            "language": "fr",
            "speech": {"plain": {"speech": text, "extra_data": None}},
            "data": {},
        },
        "conversation_id": "c1",
        "continue_conversation": False,
    }


async def _send(message: ChatMessage, answer: Any) -> tuple[ChatReply, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def process(command: dict[str, Any]) -> Any:
        sent.append(command)
        return answer

    responses = default_responses() | {"conversation/process": process}
    async with running_client(fake_home_assistant(responses)) as client:
        return await send(client, message), sent


def test_the_message_goes_to_the_chosen_agent_in_the_page_language() -> None:
    message = ChatMessage(
        text="Pourquoi 11 h ?", agent_id="conversation.llm", conversation_id="c0", language="en"
    )
    reply, sent = asyncio.run(_send(message, _answer("Parce que le soleil.")))

    assert reply == ChatReply(text="Parce que le soleil.", conversation_id="c1")
    assert sent[0]["text"] == "Pourquoi 11 h ?"
    assert sent[0]["agent_id"] == "conversation.llm"
    assert sent[0]["conversation_id"] == "c0"
    assert sent[0]["language"] == "en"


def test_without_agent_home_assistant_chooses() -> None:
    _, sent = asyncio.run(_send(ChatMessage(text="Bonjour"), _answer("Bonjour !")))

    assert "agent_id" not in sent[0] and "conversation_id" not in sent[0]


def test_an_agent_error_is_shown_as_such() -> None:
    reply = reply_of(_answer("Je n'ai pas compris.", kind="error"))

    assert reply.error and reply.text == "Je n'ai pas compris."


def test_a_refusal_from_home_assistant_is_raised() -> None:
    with pytest.raises(CommandError):
        asyncio.run(_send(ChatMessage(text="Bonjour"), None))


def test_without_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        refused = api.post("/api/assistant/chat", json={"text": "Bonjour"})
        empty = api.post("/api/assistant/chat", json={"text": ""})

    assert refused.status_code == 503
    assert empty.status_code == 422
