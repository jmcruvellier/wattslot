"""Mode de fonctionnement et configuration de l'application.

Une seule image sert deux modes (décision 1) :

- ``addon`` : lancée par le Supervisor de Home Assistant, qui fournit ``SUPERVISOR_TOKEN`` et
  donne accès à HA par le proxy ``supervisor/core`` ;
- ``standalone`` : lancée par Docker, l'adresse de HA et le jeton viennent des variables
  d'environnement (guide d'installation, ``docs/installation.md``), sinon de la connexion
  enregistrée par l'interface (``/data/home_assistant.json``, lot 4.6).
"""

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from wattslot import connection

# Accès à Home Assistant depuis une extension, par le proxy du Supervisor.
SUPERVISOR_CORE_WEBSOCKET_URL = "ws://supervisor/core/websocket"

DEFAULT_DATA_DIR = "/data"


class RunMode(StrEnum):
    ADDON = "addon"
    STANDALONE = "standalone"


@dataclass(frozen=True)
class HomeAssistantTarget:
    websocket_url: str
    token: str
    # Jeton demandé à chaque (re)connexion (OAuth2 : jeton d'accès rafraîchi) ; aucun : ``token``.
    token_provider: Callable[[], Awaitable[str]] | None = None


@dataclass(frozen=True)
class Settings:
    mode: RunMode
    data_dir: Path
    static_dir: Path | None
    home_assistant: HomeAssistantTarget | None
    # D'où vient la connexion à HA : Supervisor, environnement, interface (lot 4.6) ou aucune.
    connection_source: str | None = None
    # ``HA_URL`` sans jeton (commande du README) : adresse proposée sur la page de connexion.
    suggested_url: str | None = None


def detect_run_mode(environ: Mapping[str, str] | None = None) -> RunMode:
    """Extension HA si le Supervisor a fourni son jeton, mode autonome sinon."""
    env = os.environ if environ is None else environ
    return RunMode.ADDON if env.get("SUPERVISOR_TOKEN") else RunMode.STANDALONE


def websocket_url_from_http(url: str) -> str:
    """``http://hote:8123`` → ``ws://hote:8123/api/websocket`` (``https`` → ``wss``)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"Adresse de Home Assistant invalide : {url!r}")
    scheme = "wss" if parts.scheme == "https" else "ws"
    path = parts.path.rstrip("/") + "/api/websocket"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


def _standalone_token(env: Mapping[str, str]) -> str | None:
    """``HA_TOKEN``, ou le contenu du fichier ``HA_TOKEN_FILE`` (secret Docker, HA de test)."""
    if env.get("HA_TOKEN"):
        return env["HA_TOKEN"]
    path = env.get("HA_TOKEN_FILE")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8").strip() or None
    return None


logger = logging.getLogger(__name__)


def _variable(env: Mapping[str, str], name: str) -> str | None:
    """``WATTSLOT_<name>``, sinon l'ancien ``EO_<name>`` (avant le renommage du lot 7.1), lu
    jusqu'à la version 1.0 avec un avertissement."""
    if value := env.get(f"WATTSLOT_{name}"):
        return value
    if value := env.get(f"EO_{name}"):
        logger.warning("EO_%s est obsolète : la renommer WATTSLOT_%s", name, name)
        return value
    return None


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    mode = detect_run_mode(env)

    data_dir = Path(_variable(env, "DATA_DIR") or DEFAULT_DATA_DIR)
    target: HomeAssistantTarget | None = None
    source: str | None = None
    if mode is RunMode.ADDON:
        target = HomeAssistantTarget(SUPERVISOR_CORE_WEBSOCKET_URL, env["SUPERVISOR_TOKEN"])
        source = "supervisor"
    elif env.get("HA_URL") and (token := _standalone_token(env)):
        target = HomeAssistantTarget(websocket_url_from_http(env["HA_URL"]), token)
        source = "env"
    elif (stored := connection.load(data_dir)) is not None:
        target = HomeAssistantTarget(
            websocket_url_from_http(stored.url),
            stored.token or "",
            connection.TokenProvider(data_dir, stored),
        )
        source = "saved"

    static_dir = _variable(env, "STATIC_DIR")
    return Settings(
        mode=mode,
        data_dir=data_dir,
        static_dir=Path(static_dir) if static_dir else None,
        home_assistant=target,
        connection_source=source,
        suggested_url=(env.get("HA_URL") or None) if source is None else None,
    )
