"""Client WebSocket de Home Assistant, contre un faux serveur HA local."""

import asyncio
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from tests.fake_home_assistant import (
    ENERGY_PREFERENCES,
    TOKEN,
    VERSION,
    Handler,
    default_responses,
    fake_home_assistant,
    running_client,
)
from wattslot.home_assistant import CommandError, ConnectionState, HomeAssistantClient
from wattslot.runtime import HomeAssistantTarget


async def _connected(handler: Handler | None = None, **kwargs: Any) -> HomeAssistantClient:
    async with running_client(handler or fake_home_assistant(), **kwargs) as client:
        return client


def test_connects_and_loads_the_snapshot() -> None:
    client = asyncio.run(_connected())

    assert client.status.version == VERSION
    assert client.status.error is None
    assert client.energy_preferences == ENERGY_PREFERENCES
    assert client.snapshot.states["sensor.solar_energy"]["state"] == "1234.5"
    assert client.snapshot.entities["sensor.solar_energy"]["device_id"] == "d1"
    assert client.snapshot.devices["d1"]["name"] == "Onduleur"


def test_energy_dashboard_not_configured() -> None:
    responses = default_responses() | {"energy/get_prefs": None}

    client = asyncio.run(_connected(fake_home_assistant(responses)))

    assert client.status.state is ConnectionState.CONNECTED
    assert client.energy_preferences is None


def test_reports_a_rejected_token() -> None:
    client = asyncio.run(_connected(token="mauvais", until=ConnectionState.ERROR))

    assert client.status.error is not None
    assert "AuthenticationError" in client.status.error
    assert client.status.error_code == "token_refused"


def test_reconnects_while_home_assistant_is_still_starting() -> None:
    """Un redémarrage de HA : l'intégration Énergie n'est pas encore prête, la commande est
    refusée. La session est refermée et la connexion retentie, sans redémarrer l'application
    (essai du 05/11/2026 : seul un redémarrage du conteneur réparait la connexion)."""
    connections = 0
    ready = fake_home_assistant()
    starting = fake_home_assistant(
        default_responses() | {"energy/get_prefs": {"error": "unknown_command"}}
    )

    async def restarting(websocket: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        # Première connexion pendant le démarrage de HA, la suivante une fois prêt.
        await (starting if connections == 1 else ready)(websocket)

    client = asyncio.run(_connected(restarting))

    assert connections == 2
    assert client.status.state is ConnectionState.CONNECTED
    assert client.energy_preferences == ENERGY_PREFERENCES


def test_retry_now_interrupts_the_waiting() -> None:
    """« Vérifier à nouveau » de l'interface : le délai avant la prochaine tentative ne
    s'écoute plus, la reconnexion part aussitôt."""

    async def scenario() -> HomeAssistantClient:
        connections = 0
        ready = fake_home_assistant()

        async def down_then_ready(websocket: ServerConnection) -> None:
            nonlocal connections
            connections += 1
            if connections == 1:
                return  # HA absent : la connexion est fermée aussitôt.
            await ready(websocket)

        async with serve(down_then_ready, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            target = HomeAssistantTarget(f"ws://127.0.0.1:{port}/api/websocket", TOKEN)
            client = HomeAssistantClient(target, retry_delays=(30,))
            task = asyncio.create_task(client.run())

            async def wait_for(state: ConnectionState) -> None:
                while client.status.state is not state:
                    await asyncio.sleep(0.01)

            try:
                async with asyncio.timeout(5):
                    await wait_for(ConnectionState.ERROR)
                    client.retry_now()  # interrompt l'attente de 30 s
                    await wait_for(ConnectionState.CONNECTED)
                return client
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    client = asyncio.run(scenario())

    assert client.status.state is ConnectionState.CONNECTED
    assert client.status.version == VERSION


def test_reconnects_after_home_assistant_restarts() -> None:
    connections = 0
    handler = fake_home_assistant()

    async def restarting(websocket: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        if connections == 1:
            return  # Première connexion fermée aussitôt, comme pendant un redémarrage de HA.
        await handler(websocket)

    client = asyncio.run(_connected(restarting))

    assert connections == 2
    assert client.status.state is ConnectionState.CONNECTED


def test_concurrent_commands_get_their_own_answers() -> None:
    async def scenario() -> tuple[object, object]:
        async with running_client(fake_home_assistant()) as client:
            config, states = await asyncio.gather(
                client.command("get_config"), client.command("get_states")
            )
            return config, states

    config, states = asyncio.run(scenario())

    assert config == default_responses()["get_config"]
    assert states == default_responses()["get_states"]


def test_refused_command_raises_its_error_code() -> None:
    async def scenario() -> None:
        async with running_client(fake_home_assistant()) as client:
            await client.command("unknown/command")

    with pytest.raises(CommandError) as error:
        asyncio.run(scenario())
    assert error.value.code == "not_found"
