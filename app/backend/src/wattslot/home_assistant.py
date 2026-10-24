"""Connexion à Home Assistant par son API WebSocket.

La connexion est tenue ouverte et rétablie après chaque coupure, avec des délais croissants.
Une boucle de lecture distribue les réponses : plusieurs commandes peuvent être en cours en
même temps (API de l'application, ingestion). Les abonnements (``subscribe``) sont rétablis
automatiquement à chaque reconnexion. À chaque connexion, l'application charge un
instantané de HA (configuration, tableau Énergie, états, registres des entités et des appareils)
qui sert à la détection des rôles des entités.

Protocole : https://developers.home-assistant.io/docs/api/websocket
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from wattslot import currency
from wattslot.runtime import HomeAssistantTarget

logger = logging.getLogger(__name__)

RETRY_DELAYS_S: tuple[float, ...] = (1, 2, 5, 10, 30)
COMMAND_TIMEOUT_S = 60.0


class ConnectionState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class AuthenticationError(Exception):
    """Jeton refusé par Home Assistant."""


class ProtocolError(Exception):
    """Réponse inattendue de Home Assistant."""


class CommandError(ProtocolError):
    """Commande refusée par Home Assistant (code d'erreur de HA dans ``code``)."""

    def __init__(self, command: str, code: str | None, message: str | None) -> None:
        super().__init__(f"{command} : {code} {message}")
        self.code = code


class NotConnectedError(Exception):
    """Pas de connexion ouverte à Home Assistant."""


@dataclass(frozen=True)
class HomeAssistantStatus:
    state: ConnectionState
    version: str | None = None
    error: str | None = None
    # Code stable de la panne, pour l'interface (traduit) ; ``error`` garde le détail technique.
    error_code: str | None = None


def _code_of(exc: BaseException) -> str:
    """Code de panne compris de l'interface : détail technique dans le rapport, pas à l'écran."""
    if isinstance(exc, AuthenticationError):
        return "token_refused"
    if isinstance(exc, CommandError):
        # Commande inconnue : HA répond, mais n'a pas fini de démarrer (redémarrage, mise à jour).
        return "starting" if exc.code == "unknown_command" else "unknown"
    if isinstance(exc, ConnectionClosed):
        return "starting"
    if isinstance(exc, (OSError, TimeoutError, WebSocketException)):
        return "unreachable"
    return "unknown"


@dataclass(frozen=True)
class HomeSnapshot:
    """Ce que l'application sait de HA à la connexion (ou au dernier rafraîchissement)."""

    config: dict[str, Any] = field(default_factory=dict)
    energy_preferences: dict[str, Any] | None = None
    states: dict[str, dict[str, Any]] = field(default_factory=dict)  # par entity_id
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)  # registre, par entity_id
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)  # registre, par id


class WebSocket(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...
    def __aiter__(self) -> Any: ...


Connect = Callable[[str], AbstractAsyncContextManager[WebSocket]]
EventCallback = Callable[[dict[str, Any]], None]
ConnectedCallback = Callable[[], Awaitable[None]]


@dataclass
class _Subscription:
    command: str
    params: dict[str, Any]
    callback: EventCallback
    message_id: int | None = None  # identifiant de l'abonnement sur la connexion en cours


def _default_connect(url: str) -> AbstractAsyncContextManager[WebSocket]:
    # Les messages de HA (états de toutes les entités) dépassent la limite par défaut de 1 Mo.
    return websockets.connect(url, max_size=None)


class HomeAssistantClient:
    def __init__(
        self,
        target: HomeAssistantTarget,
        *,
        connect: Connect = _default_connect,
        retry_delays: Sequence[float] = RETRY_DELAYS_S,
    ) -> None:
        self._target = target
        self._connect = connect
        self._retry_delays = retry_delays
        self._next_id = 1
        self._websocket: WebSocket | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._subscriptions: dict[str, _Subscription] = {}
        self._events: dict[int, EventCallback] = {}
        self._on_connected_callbacks: list[ConnectedCallback] = []
        self._wake = asyncio.Event()  # ``retry_now`` interrompt le délai de reconnexion
        self.status = HomeAssistantStatus(ConnectionState.CONNECTING)
        self.snapshot = HomeSnapshot()

    @property
    def energy_preferences(self) -> dict[str, Any] | None:
        return self.snapshot.energy_preferences

    async def run(self) -> None:
        """Tient la connexion ouverte jusqu'à l'annulation de la tâche."""
        failures = 0
        while True:
            self._wake.clear()
            self.status = HomeAssistantStatus(
                ConnectionState.CONNECTING, version=self.status.version
            )
            try:
                async with self._connect(self._target.websocket_url) as websocket:
                    await self._session(websocket)
                # Fermeture propre par HA (redémarrage) : on se reconnecte.
                error, code = "connexion fermée par Home Assistant", "starting"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — toute erreur est retentée
                error, code = f"{type(exc).__name__}: {exc}", _code_of(exc)
            finally:
                self._close_session()
            if self.status.state is ConnectionState.CONNECTED:
                failures = 0  # Coupure après une connexion réussie : on repart du délai court.
            self.status = HomeAssistantStatus(
                ConnectionState.ERROR,
                version=self.status.version,
                error=error,
                error_code=code,
            )
            delay = self._retry_delays[min(failures, len(self._retry_delays) - 1)]
            failures += 1
            logger.warning("Home Assistant : %s ; nouvel essai dans %s s", error, delay)
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(delay):
                    await self._wake.wait()

    def retry_now(self) -> None:
        """Reconnexion immédiate, demandée par l'interface : le délai en cours est interrompu."""
        self._wake.set()

    async def command(self, command: str, **params: Any) -> Any:
        """Envoie une commande et attend sa réponse (``result``)."""
        websocket = self._websocket
        if websocket is None:
            raise NotConnectedError(command)
        message_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        try:
            await websocket.send(json.dumps({"id": message_id, "type": command, **params}))
            async with asyncio.timeout(COMMAND_TIMEOUT_S):
                message = await future
        finally:
            self._pending.pop(message_id, None)
        if not message.get("success"):
            error = message.get("error") or {}
            raise CommandError(command, error.get("code"), error.get("message"))
        return message.get("result")

    def on_connected(self, callback: ConnectedCallback) -> None:
        """Appelé après chaque connexion, une fois l'instantané lu et les abonnements rétablis."""
        self._on_connected_callbacks.append(callback)

    async def subscribe(
        self, name: str, command: str, callback: EventCallback, **params: Any
    ) -> None:
        """Abonnement nommé, rétabli à chaque reconnexion ; remplace un abonnement du même nom."""
        await self.unsubscribe(name)
        subscription = _Subscription(command, params, callback)
        self._subscriptions[name] = subscription
        if self._websocket is not None and self.status.state is ConnectionState.CONNECTED:
            await self._activate(subscription)

    async def unsubscribe(self, name: str) -> None:
        subscription = self._subscriptions.pop(name, None)
        if subscription is None or subscription.message_id is None:
            return
        self._events.pop(subscription.message_id, None)
        if self._websocket is not None:
            # Abonnement déjà perdu avec la connexion : rien à défaire.
            with contextlib.suppress(CommandError, NotConnectedError):
                await self.command("unsubscribe_events", subscription=subscription.message_id)

    async def _activate(self, subscription: _Subscription) -> None:
        message_id = self._next_id  # identifiant que command() va utiliser
        # Le gestionnaire est posé avant l'envoi : HA peut envoyer le premier événement aussitôt
        # après sa réponse.
        self._events[message_id] = subscription.callback
        subscription.message_id = message_id
        try:
            await self.command(subscription.command, **subscription.params)
        except Exception:
            self._events.pop(message_id, None)
            subscription.message_id = None
            raise

    async def refresh_snapshot(self) -> HomeSnapshot:
        """Relit configuration, tableau Énergie, états et registres."""
        config, states, entities, devices = await asyncio.gather(
            self.command("get_config"),
            self.command("get_states"),
            self.command("config/entity_registry/list"),
            self.command("config/device_registry/list"),
        )
        try:
            energy = await self.command("energy/get_prefs")
        except CommandError as exc:
            if exc.code != "not_found":
                raise
            energy = None
        currency.note_home_assistant((config or {}).get("currency"))
        self.snapshot = HomeSnapshot(
            config=config or {},
            energy_preferences=energy,
            states={s["entity_id"]: s for s in states or []},
            entities={e["entity_id"]: e for e in entities or []},
            devices={d["id"]: d for d in devices or []},
        )
        return self.snapshot

    async def _session(self, websocket: WebSocket) -> None:
        await self._authenticate(websocket)
        self._websocket = websocket
        loading = asyncio.create_task(self._on_connected())
        try:
            async for raw in websocket:
                self._dispatch(raw)
        finally:
            loading.cancel()
            results = await asyncio.gather(loading, return_exceptions=True)
        # L'instantané n'a pas pu être lu (HA démarre, commande refusée…) : la session est
        # fermée pour que ``run`` en ouvre une autre, au lieu de rester connecté sans état.
        failure = next(
            (
                result
                for result in results
                if isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError)
            ),
            None,
        )
        if failure is not None:
            raise failure

    async def _on_connected(self) -> None:
        try:
            snapshot = await self.refresh_snapshot()
        except Exception:
            # Instantané illisible (HA démarre, une commande est refusée…) : la session est
            # refermée pour que ``run`` en ouvre une autre, au lieu de rester connecté sans
            # rien savoir de la maison (seul un redémarrage réparait la connexion).
            websocket = self._websocket
            if websocket is not None:
                with contextlib.suppress(Exception):
                    await websocket.close()
            raise
        version = snapshot.config.get("version")
        self.status = HomeAssistantStatus(ConnectionState.CONNECTED, version=version)
        for subscription in list(self._subscriptions.values()):
            try:
                await self._activate(subscription)
            except Exception as exc:  # noqa: BLE001 — rapporté, les autres continuent
                logger.warning("Abonnement %s refusé : %s", subscription.command, exc)
        for callback in self._on_connected_callbacks:
            try:
                await callback()
            except Exception:
                logger.exception("Erreur après la connexion à Home Assistant")
        logger.info("Connecté à Home Assistant %s (%s entités)", version, len(snapshot.states))

    def _dispatch(self, raw: str | bytes) -> None:
        message = json.loads(raw)
        if not isinstance(message, dict):
            return
        message_id = message.get("id", -1)
        if message.get("type") == "event":
            callback = self._events.get(message_id)
            if callback is not None:
                try:
                    callback(message.get("event") or {})
                except Exception:
                    logger.exception("Erreur dans le traitement d'un événement")
            return
        future = self._pending.get(message_id)
        if future is not None and not future.done() and message.get("type") == "result":
            future.set_result(message)

    def _close_session(self) -> None:
        self._websocket = None
        self._events.clear()
        for subscription in self._subscriptions.values():
            subscription.message_id = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(NotConnectedError("connexion perdue"))
        self._pending.clear()

    async def _authenticate(self, websocket: WebSocket) -> None:
        message = await _receive(websocket)
        if message.get("type") != "auth_required":
            raise ProtocolError(f"attendu auth_required, reçu {message.get('type')!r}")
        provider = self._target.token_provider
        token = await provider() if provider is not None else self._target.token
        await websocket.send(json.dumps({"type": "auth", "access_token": token}))
        message = await _receive(websocket)
        if message.get("type") == "auth_invalid":
            raise AuthenticationError(message.get("message", "jeton refusé"))
        if message.get("type") != "auth_ok":
            raise ProtocolError(f"attendu auth_ok, reçu {message.get('type')!r}")


async def _receive(websocket: WebSocket) -> dict[str, Any]:
    raw = await websocket.recv()
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise ProtocolError(f"message inattendu : {raw!r}")
    return message
