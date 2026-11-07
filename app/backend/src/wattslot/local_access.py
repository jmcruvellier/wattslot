"""Accès en mode autonome : réseau local seulement, sans connexion de l'utilisateur.

En extension, ``ingress.py`` n'admet que le proxy d'ingress. En autonome, l'application écoute
sur le réseau local sans mot de passe ; deux attaques depuis une page web ouverte par quelqu'un
de la maison sont écartées ici :

- **rebinding DNS** : un nom de domaine public qui se met à pointer vers l'adresse locale de
  WattSlot. Le navigateur l'envoie dans l'en-tête ``Host`` : on n'admet que les adresses IP, les
  noms sans point (``nas``), les suffixes réservés aux réseaux locaux, et les noms de
  ``WATTSLOT_ALLOWED_HOSTS`` (proxy inverse, nom de domaine local) ;
- **requête intersite** : une autre page qui envoie un formulaire ou un ``fetch`` en écriture.
  Une écriture dont l'en-tête ``Origin`` n'est pas l'adresse de WattSlot est refusée.

Ce n'est pas une authentification : un appareil du réseau local garde l'accès (guide
d'installation, ``SECURITY.md``).
"""

import ipaddress
import logging
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Suffixes réservés aux réseaux privés (RFC 6762, 8375, 6761 ; .lan et .internal d'usage courant).
LOCAL_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".localdomain", ".localhost")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ALLOWED_HOSTS_VARIABLE = "WATTSLOT_ALLOWED_HOSTS"


def _hostname(host: str) -> str:
    """Nom d'hôte de l'en-tête ``Host`` (sans port, sans crochets IPv6), en minuscules."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host[1:]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def local_host(host: str, allowed: frozenset[str] = frozenset()) -> bool:
    """``host`` (en-tête ``Host``) désigne WattSlot sur le réseau local, ou un nom admis."""
    name = _hostname(host)
    if not name:
        return False
    if "*" in allowed or name in allowed:
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return "." not in name or name.endswith(LOCAL_SUFFIXES)


def parse_allowed(value: str | None) -> frozenset[str]:
    """``WATTSLOT_ALLOWED_HOSTS`` : noms séparés par des virgules (``*`` : tous)."""
    return frozenset(_hostname(item) for item in (value or "").split(",") if item.strip())


def same_site(origin: str, host: str, allowed: frozenset[str] = frozenset()) -> bool:
    """L'en-tête ``Origin`` est l'adresse de WattSlot : même hôte, ou un nom admis (proxy
    inverse qui réécrit ``Host`` vers l'adresse interne)."""
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https"):
        return False
    return parts.netloc.lower() == host.strip().lower() or _hostname(parts.netloc) in allowed


class LocalAccessMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = Headers(scope=scope)
            host = headers.get("host", "")
            reason = None
            if not local_host(host, self.allowed_hosts):
                reason = "host"
                logger.warning(
                    "Requête refusée pour l'hôte %r : l'ajouter à %s si c'est le vôtre",
                    host,
                    ALLOWED_HOSTS_VARIABLE,
                )
            elif scope["type"] == "websocket" or scope.get("method") not in SAFE_METHODS:
                origin = headers.get("origin")
                if origin is not None and not same_site(origin, host, self.allowed_hosts):
                    reason = "origin"
            if reason is not None:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    response = PlainTextResponse("Accès refusé", status_code=403)
                    await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
