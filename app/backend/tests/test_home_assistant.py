"""Client WebSocket de Home Assistant, contre un faux serveur HA local."""

import asyncio
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection

from tests.fake_home_assistant import (
    ENERGY_PREFERENCES,
    VERSION,
    Handler,
    default_responses,
    fake_home_assistant,
    running_client,
)
from wattslot.home_assistant import CommandError, ConnectionState, HomeAssistantClient


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
