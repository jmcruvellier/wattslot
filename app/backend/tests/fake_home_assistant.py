"""Faux serveur Home Assistant (API WebSocket) pour les tests.

Répond à l'authentification et aux commandes de ``RESPONSES`` ; une valeur ``None`` dans les
réponses produit l'erreur ``not_found`` (tableau Énergie non configuré, par exemple), une
valeur ``{"error": "code"}`` produit cette erreur (``unknown_command`` au démarrage, par
exemple).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.runtime import HomeAssistantTarget

TOKEN = "jeton-de-test"
VERSION = "2026.10.1"

ENERGY_PREFERENCES: dict[str, object] = {
    "energy_sources": [{"type": "solar", "stat_energy_from": "sensor.solar_energy"}],
    "device_consumption": [],
}


def default_responses() -> dict[str, Any]:
    return {
        "get_config": {"version": VERSION, "time_zone": "Europe/Paris"},
        "energy/get_prefs": ENERGY_PREFERENCES,
        "get_states": [
            {
                "entity_id": "sensor.solar_energy",
                "state": "1234.5",
                "attributes": {"unit_of_measurement": "kWh", "device_class": "energy"},
            }
        ],
        "config/entity_registry/list": [
            {"entity_id": "sensor.solar_energy", "device_id": "d1", "platform": "demo"}
        ],
        "config/device_registry/list": [{"id": "d1", "name": "Onduleur"}],
    }


Handler = Callable[[ServerConnection], Awaitable[None]]


class Subscriptions:
    """Abonnements ouverts sur le faux HA, pour y pousser des événements depuis les tests."""

    def __init__(self) -> None:
        self.active: list[tuple[ServerConnection, int, dict[str, Any]]] = []

    async def push(self, event: dict[str, Any]) -> None:
        for websocket, message_id, _ in self.active:
            await websocket.send(json.dumps({"id": message_id, "type": "event", "event": event}))


def fake_home_assistant(
    responses: dict[str, Any] | None = None, subscriptions: Subscriptions | None = None
) -> Handler:
    answers = default_responses() if responses is None else responses

    async def handler(websocket: ServerConnection) -> None:
        await websocket.send(json.dumps({"type": "auth_required", "ha_version": VERSION}))
        auth = json.loads(await websocket.recv())
        if auth.get("access_token") != TOKEN:
            await websocket.send(
                json.dumps({"type": "auth_invalid", "message": "Invalid access token"})
            )
            return
        await websocket.send(json.dumps({"type": "auth_ok", "ha_version": VERSION}))
        async for raw in websocket:
            message = json.loads(raw)
            reply: dict[str, Any] = {"id": message["id"], "type": "result"}
            if message["type"] == "subscribe_entities":
                await websocket.send(json.dumps(reply | {"success": True, "result": None}))
                wanted = set(message.get("entity_ids") or [])
                states = {
                    s["entity_id"]: {
                        "s": s["state"],
                        "a": s.get("attributes", {}),
                        "lc": s.get("lc", 1_760_000_000.0),
                    }
                    for s in answers.get("get_states") or []
                    if not wanted or s["entity_id"] in wanted
                }
                event = {"id": message["id"], "type": "event", "event": {"a": states}}
                await websocket.send(json.dumps(event))
                if subscriptions is not None:
                    subscriptions.active.append((websocket, message["id"], message))
                continue
            answer = answers.get(message["type"])
            if callable(answer):  # réponse qui dépend des paramètres de la commande
                answer = answer(message)
            if isinstance(answer, dict) and "error" in answer:
                reply |= {
                    "success": False,
                    "error": {"code": answer["error"], "message": answer.get("message", "?")},
                }
            elif answer is not None:
                reply |= {"success": True, "result": answer}
            else:
                reply |= {"success": False, "error": {"code": "not_found", "message": "?"}}
            await websocket.send(json.dumps(reply))

    return handler


@asynccontextmanager
async def running_client(
    handler: Handler,
    token: str = TOKEN,
    until: ConnectionState = ConnectionState.CONNECTED,
    token_provider: Callable[[], Awaitable[str]] | None = None,
) -> AsyncIterator[HomeAssistantClient]:
    """Client connecté au faux HA, une fois l'état ``until`` atteint."""
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        target = HomeAssistantTarget(f"ws://127.0.0.1:{port}/api/websocket", token, token_provider)
        client = HomeAssistantClient(target, retry_delays=(0.05,))
        task = asyncio.create_task(client.run())
        try:
            async with asyncio.timeout(5):
                while client.status.state is not until:
                    await asyncio.sleep(0.01)
            yield client
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
