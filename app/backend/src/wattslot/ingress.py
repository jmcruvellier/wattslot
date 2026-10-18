"""Accès à l'application en mode extension.

Le Supervisor publie l'interface par son ingress, authentifiée par Home Assistant ; aucun port
n'est publié. Le conteneur reste joignable par les autres extensions du réseau interne de HA :
on n'y répond donc qu'au proxy d'ingress, et à la machine elle-même pour le HEALTHCHECK de
l'image. Exception : le serveur MCP (``/mcp``, lot 6.1), que l'intégration « Model Context
Protocol » de HA Core appelle directement, sans l'ingress.

https://developers.home-assistant.io/docs/add-ons/presentation#ingress
"""

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SUPERVISOR_INGRESS_ADDRESS = "172.30.32.2"
HOME_ASSISTANT_CORE_ADDRESS = "172.30.32.1"
ALLOWED_ADDRESSES = frozenset({SUPERVISOR_INGRESS_ADDRESS, "127.0.0.1", "::1"})
MCP_PATH = "/mcp"


class IngressOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            address = client[0] if client else None
            core_to_mcp = address == HOME_ASSISTANT_CORE_ADDRESS and (
                scope.get("path") == MCP_PATH
                or str(scope.get("path", "")).startswith(MCP_PATH + "/")
            )
            if address not in ALLOWED_ADDRESSES and not core_to_mcp:
                response = PlainTextResponse("Accès réservé à l'ingress", status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
