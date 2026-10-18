"""Serveur MCP de l'application (lot 6.1), monté sur ``/mcp`` (Streamable HTTP).

SDK officiel ``mcp`` (point n° 3 de la phase 6). Sans état et en réponses JSON : aucune session
gardée en mémoire, des échanges simples. La protection contre le détournement DNS du SDK, qui
n'accepte par défaut que « localhost », est levée : Home Assistant joint l'application par son
adresse sur le réseau local, comme l'interface (point n° 2). En mode extension, seul HA Core y
accède (``ingress.py``).
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.routing import BaseRoute

from wattslot import __version__
from wattslot.assistant import tools

PATH = "/mcp"
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# Seule action (point n° 5) : déposer une demande, sans rien effacer ; la redéposer ne change
# que sa date.
REQUEST = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

INSTRUCTIONS = (
    "WattSlot, for a home with solar panels: daily plan of the appliances and battery, "
    "computed without you. Read the plan and its explanations with the tools; never invent "
    "times or figures. Texts in the answers are already written in the user's language."
)


def build(state: Callable[[], Any], problems: Callable[[], Awaitable[Sequence[Any]]]) -> MCPServer:
    """Serveur et ses outils ; ``state`` rend l'état de l'application (``app.state``) au moment
    de l'appel, ``problems`` les problèmes du diagnostic."""
    server: MCPServer = MCPServer(name="wattslot", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    async def get_day_plan(day: tools.Day = "today") -> dict[str, Any]:
        """Plan of a day: recommendation text, key figures, warnings."""
        return await tools.get_day_plan(state(), day)

    @server.tool(annotations=READ_ONLY)
    async def explain_device(device: str, day: tools.Day = "today") -> dict[str, Any]:
        """Why and when an appliance is planned, and whether it started on time."""
        return await tools.explain_device(state(), device, day)

    @server.tool(annotations=READ_ONLY)
    async def get_week() -> dict[str, Any]:
        """The next days: production, weather, planned appliances."""
        return await tools.get_week(state())

    @server.tool(annotations=READ_ONLY)
    def get_current_status() -> dict[str, Any]:
        """Latest readings: battery level, solar and appliance power."""
        return tools.get_current_status(state())

    @server.tool(annotations=READ_ONLY)
    async def get_energy(day: str = "today") -> dict[str, Any]:
        """Measured energy of a day (today, yesterday or YYYY-MM-DD), and the plan if any."""
        return await tools.get_energy(state(), day)

    @server.tool(annotations=READ_ONLY)
    async def get_forecast(day: Literal["today", "tomorrow"] = "today") -> dict[str, Any]:
        """Weather and solar production forecast, hour by hour."""
        return await tools.get_forecast(state(), day)

    @server.tool(annotations=READ_ONLY)
    def get_home() -> dict[str, Any]:
        """Appliances of the home and how they are planned, tariff, objective."""
        return tools.get_home(state())

    @server.tool(annotations=READ_ONLY)
    async def get_problems() -> dict[str, Any]:
        """What is wrong with the application, most serious first."""
        return await tools.get_problems(problems)

    @server.tool(annotations=REQUEST)
    def request_device(device: str, latest_date: str | None = None) -> dict[str, Any]:
        """Ask to run an appliance at the best time, by latest_date (YYYY-MM-DD) if given."""
        return tools.request_device(state(), device, latest_date)

    return server


def routes(server: MCPServer) -> list[BaseRoute]:
    """Route ``/mcp`` à ajouter à l'application ; le gestionnaire de sessions du serveur doit
    tourner (``server.session_manager.run()``) pendant toute sa vie."""
    app = server.streamable_http_app(
        streamable_http_path=PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return list(app.routes)
