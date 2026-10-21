"""Point d'entrée de l'application : API, connexion à Home Assistant, interface.

Lancement en développement :

    uvicorn wattslot.main:app --reload --port 8100
"""

import asyncio
import contextlib
import logging
import os
import signal
import sqlite3
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.types import Scope

from wattslot import (
    __version__,
    addon_options,
    backup,
    configuration,
    connection,
    currency,
    exchange,
    home_model,
    notifications,
    profiles,
    report,
    templates,
    user_requests,
)
from wattslot.aggregation import PERIODS, Aggregate, AggregationStatus, Aggregator
from wattslot.assistant import chat as assistant_chat
from wattslot.assistant import home_config as assistant_home_config
from wattslot.assistant import open_webui
from wattslot.assistant import prompts as assistant_prompts
from wattslot.assistant import server as assistant_server
from wattslot.corrections import CorrectionStore
from wattslot.detection import (
    DeviceKind,
    EntityChoice,
    HomeProposal,
    Role,
    propose,
    sensor_choices,
)
from wattslot.diagnostic import Diagnostic, diagnostic
from wattslot.energy import EnergySources, energy_sources
from wattslot.home_assistant import (
    CommandError,
    ConnectionState,
    HomeAssistantClient,
    NotConnectedError,
)
from wattslot.ingestion import IngestionStatus, Ingestor
from wattslot.ingress import IngressOnlyMiddleware
from wattslot.maintenance import (
    Maintenance,
    MaintenanceRun,
    MaintenanceStatus,
    Retention,
    load_retention,
    save_retention,
)
from wattslot.ontology import GRAPH_CONFIGURATION, GRAPH_HOME
from wattslot.ontology import migration as ontology_migration
from wattslot.planning import journal, open_meteo, past
from wattslot.planning.assemble import TaskRules, build_input, rules_from_tasks, to_v1
from wattslot.planning.choices import router as choices_routes
from wattslot.planning.cycles import Segment
from wattslot.planning.journal import CycleJournal, cycle_appliances
from wattslot.planning.runner import Context, RunReport, refresh_actual, run, stored_plan
from wattslot.planning.scheduler import PlanningScheduler, SchedulerStatus
from wattslot.planning.sources import (
    Forecasts,
    ForecastUnavailable,
    PlanningSettings,
    has_production,
    read_tasks,
)
from wattslot.planning.sources import (
    load_settings as load_planning_settings,
)
from wattslot.planning.sources import (
    save_settings as save_planning_settings,
)
from wattslot.planning.store import PLAN_KINDS, PlanStore
from wattslot.problems import Problem, collect
from wattslot.quality import Monitor as QualityMonitor
from wattslot.quality import router as quality_routes
from wattslot.reminders import ReminderLoop
from wattslot.reminders import router as reminders_routes
from wattslot.runtime import RunMode, Settings, load_settings
from wattslot.settings_choices import SettingsChoices, settings_choices
from wattslot.setup import Setup, setup_status
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import RawStores
from wattslot.tariff import Tariff
from wattslot.tariff import propose as propose_tariff
from wattslot.templates import Preview, TariffEntities
from wattslot.views import layout as views_layout
from wattslot.views import routes as views_routes

logger = logging.getLogger(__name__)


class ConfigurationCheck(BaseModel):
    issues: list[configuration.Issue]


class HomeAssistantHealth(BaseModel):
    state: ConnectionState
    version: str | None = None
    error: str | None = None


class Connections(BaseModel):
    home_assistant: HomeAssistantHealth


class PlanningHistory(BaseModel):
    day: date
    baseline_kwh: dict[int, float]
    best_production: past.BestProduction | None
    recent_history: past.RecentHistory | None
    battery_efficiencies: past.BatteryEfficiencies
    cycle_profiles: dict[str, dict[str, Any]]  # par équipement : profil et sources
    real_cycles: dict[str, tuple[Segment, ...]]  # cycles réels du jour


class Health(BaseModel):
    version: str
    mode: RunMode
    connections: Connections


class HealthCheckFilter(logging.Filter):
    """Retire des journaux d'accès d'uvicorn les appels à ``/api/health``.

    Le HEALTHCHECK de l'image l'interroge toutes les 30 secondes : ces lignes noyaient les
    journaux utiles.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        return not (isinstance(args, tuple) and len(args) >= 3 and args[2] == "/api/health")


def configure_logging(level: str = "info") -> None:
    """Journaux de l'application (connexion à HA, erreurs) sur la sortie standard.

    Uvicorn ne configure que ses propres journaux : sans cela, seuls les avertissements de
    l'application sortiraient. ``level`` : option de l'extension (``addon_options.py``).
    """
    logger = logging.getLogger("wattslot")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(level.upper())
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, HealthCheckFilter) for f in access.filters):
        access.addFilter(HealthCheckFilter())


class ConnectionInfo(BaseModel):
    mode: RunMode
    source: str | None  # supervisor, env, saved ; aucune : pas de connexion
    # Connexion enregistrée par l'interface ; sans connexion, ``HA_URL`` à proposer.
    url: str | None = None
    method: str | None = None  # oauth ou token
    state: ConnectionState
    error: str | None = None


class TokenLogin(BaseModel):
    url: str
    token: str


class OAuthLogin(BaseModel):
    url: str
    client_id: str  # adresse de l'application, vue du navigateur


class RequestableDevice(BaseModel):
    key: str
    name: str


class NewRequest(BaseModel):
    device: str  # clé de l'équipement
    latest: date | None = None  # au plus tard ; aucun : dès que possible


class TemplateSummary(BaseModel):
    key: str
    name: dict[str, str]
    description: dict[str, str]
    tariff_kind: str
    devices: list[str]  # équipements de la maison que le modèle réglerait


class InterfaceFiles(StaticFiles):
    """Interface compilée (lot 7.1) : la page d'accueil est revalidée à chaque visite, pour qu'une
    mise à jour de l'application soit vue aussitôt ; les fichiers de ``assets/``, dont le nom porte
    l'empreinte du contenu (Vite), sont gardés un an par le navigateur."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        immutable = path.replace("\\", "/").startswith("assets/")
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if immutable else "no-cache"
        )
        return response


async def _notify(
    client: HomeAssistantClient,
    database: sqlite3.Connection,
    now: datetime,
    zone: ZoneInfo,
    report: RunReport,
) -> None:
    """Notifications activées, envoyées après un calcul planifié (lot 5.6) ; l'échec de l'une
    est noté dans le bilan du calcul sans empêcher les autres."""
    before = len(report.errors)
    try:
        await notifications.dispatch(client, database, now, zone, report.errors)
    except Exception as exc:  # noqa: BLE001 — noté dans le bilan, comme les autres échecs
        report.errors.append(f"notification : {type(exc).__name__}: {exc}")
    for error in report.errors[before:]:
        logger.warning("Notification impossible : %s", error)


def _scheduler(
    client: HomeAssistantClient,
    graph: GraphStore,
    aggregator: Aggregator,
    raw: RawStores,
    database: sqlite3.Connection,
    lock: asyncio.Lock,
    data_dir: Path | None = None,
) -> PlanningScheduler:
    """Planificateur des calculs : réglages relus à chaque tour, HA connecté exigé (sauf pour
    relire les données réelles, lues sur le brut)."""

    async def runner(now: datetime) -> RunReport:
        if client.status.state is not ConnectionState.CONNECTED:
            raise RuntimeError("Home Assistant non connecté")
        context = Context(
            client=client,
            model=home_model.load(graph),
            reader=aggregator,
            raw=raw,
            database=database,
            settings=load_planning_settings(database),
            configuration=configuration.load(graph),
            data_dir=data_dir,
        )
        report = await run(context, now)
        await _notify(client, database, now, raw.zone, report)
        return report

    async def refresher(now: datetime) -> None:
        await asyncio.to_thread(
            refresh_actual,
            home_model.load(graph),
            raw,
            database,
            now,
            configuration.load(graph),
            manual=False,
        )

    def settings() -> tuple[bool, int, int]:
        current = load_planning_settings(database)
        return current.scheduler_enabled, current.run_minute, current.actual_refresh_minutes

    def today_plan_day() -> date | None:
        plan = PlanStore(database).load("today")
        return plan.day if plan else None

    return PlanningScheduler(runner, settings, lambda: raw.zone, today_plan_day, lock, refresher)


class LibraryType(BaseModel):
    """Type de la bibliothèque, tel que l'onglet « Bibliothèque » le présente (lot 2t.2)."""

    kind: DeviceKind
    behaviors: list[configuration.Behavior]  # comportements permis, le premier par défaut
    roles: list[Role]  # rôles attendus de ses capteurs
    subtypes: bool  # accepte des types propres


class DeviceTypes(BaseModel):
    parents: list[DeviceKind]  # types de la bibliothèque qui acceptent des sous-types
    types: list[home_model.DeviceType]  # types propres à l'installation
    library: list[LibraryType] = []  # tous les types de la bibliothèque


class TypeName(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class NewDeviceType(TypeName):
    parent: DeviceKind


def _save_home(graph: GraphStore, model: home_model.HomeModel) -> None:
    """Enregistre le modèle s'il est valide ; 422 avec ses anomalies sinon."""
    issues = home_model.problems(model)
    if issues:
        detail = [{"code": c, "device": k, "params": p} for c, k, p in issues]
        raise HTTPException(status_code=422, detail=detail)
    home_model.save(graph, model)


def _keep_types(model: home_model.HomeModel, saved: home_model.HomeModel) -> home_model.HomeModel:
    """Garde les types propres enregistrés quand la requête ne les porte pas (lot 2t.1)."""
    if "types" not in model.model_fields_set:
        model = model.model_copy(update={"types": saved.types})
    before = {d.key: d for d in saved.devices}
    devices = []
    for device in model.devices:
        old = before.get(device.key)
        if (
            "custom_type" not in device.model_fields_set
            and old is not None
            and old.kind is device.kind
        ):
            device = device.model_copy(update={"custom_type": old.custom_type})
        devices.append(device)
    return model.model_copy(update={"devices": devices})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    # Options réglées dans HA (lot 6t.3), en mode extension seulement.
    options = addon_options.load(settings.data_dir) if settings.mode is RunMode.ADDON else None
    configure_logging(options.log_level if options else "info")

    # Serveur MCP (lot 6.1) : outils lus sur l'état de l'application au moment de l'appel.
    async def mcp_problems() -> list[Problem]:
        return (await current_problems_of(app.state))[1]

    mcp_server = assistant_server.build(lambda: app.state, mcp_problems)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run(), _lifespan(app):
            yield

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        backup.restore_snapshot(settings.data_dir)  # après une restauration de HA
        database = open_database(settings.data_dir)
        currency.use_saved(currency.load(database).code)
        if options is not None:
            retention = addon_options.apply_retention(database, options)
            logger.info(
                "Options de l'extension : journaux %s, brut %s jours, quarts d'heure %s jours",
                options.log_level,
                retention.raw_days,
                retention.quarter_days,
            )
        graph = GraphStore(settings.data_dir)
        # Données d'avant le renommage en WattSlot (lot 7.1) : maison et réglages réécrits.
        ontology_migration.migrate(graph, database)
        home_model.load_vocabulary(graph)
        client = HomeAssistantClient(settings.home_assistant) if settings.home_assistant else None
        raw = RawStores(settings.data_dir)
        # Relevés bruts d'avant le renommage en WattSlot (lot 7.1) : capteurs réécrits.
        ontology_migration.migrate_raw(raw)
        ingestor = Ingestor(client, raw, database) if client else None
        aggregator = Aggregator(ingestor, raw, graph, database, client) if ingestor else None
        task = asyncio.create_task(client.run()) if client else None
        if ingestor:
            await ingestor.start(home_model.load(graph))
        if aggregator:
            aggregator.start()
        # Qualité des données : les sauts de compteur écartés dès qu'ils sont calculés.
        quality_monitor = (
            QualityMonitor(aggregator, CorrectionStore(database), graph, aggregator.recompute)
            if aggregator
            else None
        )
        if quality_monitor:
            quality_monitor.start()
        maintenance = (
            Maintenance(raw, graph, database, settings.data_dir, aggregator) if aggregator else None
        )
        if maintenance:
            maintenance.start()
        app.state.database = database
        app.state.graph = graph
        app.state.home_assistant = client
        app.state.ingestor = ingestor
        app.state.raw = raw
        app.state.aggregator = aggregator
        app.state.quality = quality_monitor
        app.state.planning_lock = asyncio.Lock()
        app.state.maintenance = maintenance
        scheduler = None
        if client is not None and aggregator is not None:
            scheduler = _scheduler(
                client,
                graph,
                aggregator,
                raw,
                database,
                app.state.planning_lock,
                settings.data_dir,
            )
            scheduler.start()
        app.state.scheduler = scheduler
        # Anciens agrégats (lot 7.1), vidés en arrière-plan : l'application répond pendant ce temps.
        cleanup_stop = threading.Event()
        cleanup = asyncio.create_task(
            asyncio.to_thread(ontology_migration.drop_legacy_aggregates, graph, cleanup_stop)
        )
        # Rappels « Me le rappeler » (lot 6b.3), envoyés à l'heure par une boucle d'une minute.
        reminder_loop = ReminderLoop(client, database, raw.zone) if client is not None else None
        if reminder_loop:
            reminder_loop.start()
        try:
            yield
        finally:
            began = time.monotonic()
            cleanup_stop.set()
            with contextlib.suppress(Exception):
                await cleanup
            if reminder_loop:
                await reminder_loop.stop()
            if scheduler:
                await scheduler.stop()
            if maintenance:
                await maintenance.stop()
            if quality_monitor:
                await quality_monitor.stop()
            if aggregator:
                await aggregator.stop()
            if ingestor:
                await ingestor.stop()
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            graph.flush()
            database.close()
            logger.info("Arrêt : écritures vidées en %.1f s", time.monotonic() - began)

    app = FastAPI(title="WattSlot", version=__version__, lifespan=lifespan)
    app.router.routes.extend(assistant_server.routes(mcp_server))
    app.state.mcp = mcp_server
    app.include_router(assistant_prompts.router)
    app.include_router(reminders_routes)
    app.include_router(quality_routes)
    app.include_router(choices_routes)

    @app.get("/api/assistant/connection")
    def assistant_connection(request: Request) -> assistant_prompts.AssistantConnection:
        """Adresse du serveur MCP à donner à l'intégration « Model Context Protocol » de HA
        (lot 6.3) : celle retenue, sinon, en extension, celle que HA Core joint sur le réseau
        interne ; en mode autonome, aucune tant que la page ne l'a pas retenue."""
        saved = assistant_prompts.load_address(request.app.state.database)
        return assistant_prompts.connection(settings.mode, saved=saved)

    @app.put("/api/assistant/connection")
    def save_assistant_connection(
        request: Request, body: assistant_prompts.McpAddress
    ) -> assistant_prompts.AssistantConnection:
        """Retient (ou oublie, ``null``) l'adresse interne du serveur MCP ; 422 si ce n'est pas
        une adresse http(s)."""
        database = request.app.state.database
        try:
            assistant_prompts.save_address(database, body.mcp_url)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        saved = assistant_prompts.load_address(database)
        return assistant_prompts.connection(settings.mode, saved=saved)

    if settings.mode is RunMode.ADDON:
        app.add_middleware(IngressOnlyMiddleware)

    @app.get("/api/health")
    def health(request: Request) -> Health:
        client: HomeAssistantClient | None = request.app.state.home_assistant
        if client is None:
            ha = HomeAssistantHealth(state=ConnectionState.NOT_CONFIGURED)
        else:
            ha = HomeAssistantHealth(
                state=client.status.state, version=client.status.version, error=client.status.error
            )
        return Health(
            version=__version__, mode=settings.mode, connections=Connections(home_assistant=ha)
        )

    @app.get("/api/energy/sources")
    def sources(request: Request) -> EnergySources:
        client: HomeAssistantClient | None = request.app.state.home_assistant
        return energy_sources(client.energy_preferences if client else None)

    def connected_client(request: Request) -> HomeAssistantClient:
        client: HomeAssistantClient | None = request.app.state.home_assistant
        if client is None or client.status.state is not ConnectionState.CONNECTED:
            raise HTTPException(status_code=503, detail="Home Assistant non connecté")
        return client

    @app.get("/api/assistant/home")
    async def get_assistant_home(request: Request) -> assistant_home_config.AssistantHomeConfig:
        """Configuration de l'assistant vocal dans HA : intégration MCP, assistants, agents de
        conversation ; vide sans HA connecté."""
        return await assistant_home_config.home_config(request.app.state.home_assistant)

    @app.put("/api/assistant/home")
    async def put_assistant_home(
        request: Request, wanted: assistant_home_config.AssistantChange
    ) -> assistant_home_config.AssistantHomeConfig:
        """Assistant préféré de HA et son agent de conversation ; 422 pour un choix que HA ne
        connaît pas, 503 sans HA connecté, 502 si HA refuse la modification."""
        client = connected_client(request)
        try:
            await assistant_home_config.change(client, wanted)
        except assistant_home_config.UnknownChoiceError as error:
            raise HTTPException(status_code=422, detail="Assistant ou agent inconnu") from error
        except (CommandError, NotConnectedError, TimeoutError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return await assistant_home_config.home_config(client)

    @app.get("/api/assistant/open-webui")
    def get_open_webui(request: Request) -> open_webui.OpenWebUIState:
        """Réglage d'Open WebUI : l'adresse, et seulement s'il y a une clé d'API."""
        return open_webui.state(open_webui.load(request.app.state.database))

    @app.put("/api/assistant/open-webui")
    def put_open_webui(
        request: Request, change: open_webui.OpenWebUIChange
    ) -> open_webui.OpenWebUIState:
        """Adresse et clé d'API d'Open WebUI ; sans clé saisie, la clé actuelle est gardée."""
        database = request.app.state.database
        setting = open_webui.merged(open_webui.load(database), change)
        open_webui.save(database, setting)
        return open_webui.state(setting)

    @app.post("/api/assistant/open-webui/test")
    async def test_open_webui(
        request: Request, change: open_webui.OpenWebUIChange
    ) -> list[open_webui.Model]:
        """Modèles d'Open WebUI avec le réglage du formulaire, sans l'enregistrer ; 502 avec
        la raison si Open WebUI ne répond pas."""
        setting = open_webui.merged(open_webui.load(request.app.state.database), change)
        try:
            return await asyncio.to_thread(open_webui.models, setting)
        except open_webui.OpenWebUIError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/assistant/open-webui/models")
    async def open_webui_models(request: Request) -> list[open_webui.Model]:
        """Modèles d'Open WebUI pour le chat ; liste vide sans réglage ou s'il ne répond pas."""
        setting = open_webui.load(request.app.state.database)
        if not setting.ready:
            return []
        try:
            return await asyncio.to_thread(open_webui.models, setting)
        except open_webui.OpenWebUIError:
            return []

    @app.post("/api/assistant/chat")
    async def post_assistant_chat(
        request: Request, message: assistant_chat.ChatMessage
    ) -> assistant_chat.ChatReply:
        """Message de la page Assistant, transmis à un agent de conversation de HA, ou à un
        modèle d'Open WebUI (agent « open_webui:<modèle> ») ; 503 sans HA connecté (ou sans
        Open WebUI configuré), 502 si l'un ou l'autre refuse ou ne répond pas à temps."""
        agent = message.agent_id or ""
        if agent.startswith(open_webui.AGENT_PREFIX):
            setting = open_webui.load(request.app.state.database)
            if not setting.ready:
                raise HTTPException(status_code=503, detail="Open WebUI non configuré")
            try:
                text = await asyncio.to_thread(
                    open_webui.complete,
                    setting,
                    agent.removeprefix(open_webui.AGENT_PREFIX),
                    assistant_prompts.prompt(message.language),
                    message.history,
                    message.text,
                )
            except open_webui.OpenWebUIError as error:
                raise HTTPException(status_code=502, detail=str(error)) from error
            return assistant_chat.ChatReply(text=text)
        client = connected_client(request)
        try:
            return await assistant_chat.send(client, message)
        except (CommandError, NotConnectedError, TimeoutError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/home/proposals")
    async def proposals(request: Request, refresh: bool = False) -> HomeProposal:
        """Rôles proposés pour les entités, d'après le tableau Énergie et les registres de HA."""
        client = connected_client(request)
        snapshot = await client.refresh_snapshot() if refresh else client.snapshot
        return propose(snapshot)

    @app.get("/api/home/entities")
    def home_entities(request: Request) -> list[EntityChoice]:
        """Capteurs de HA qu'on peut lier à un équipement ajouté à la main, avec leurs rôles
        possibles (lot 2t.2) ; 503 sans HA connecté."""
        return sensor_choices(connected_client(request).snapshot)

    @app.get("/api/home")
    def get_home(request: Request) -> home_model.HomeModel:
        """Modèle de la maison validé (vide tant que rien n'a été validé)."""
        return home_model.load(request.app.state.graph)

    @app.put("/api/home")
    async def put_home(request: Request, model: home_model.HomeModel) -> home_model.HomeModel:
        """Enregistre le modèle de la maison. Les types propres et le type propre d'un équipement
        absents de la requête (formulaire qui ne les connaît pas) sont gardés ; 422 avec les
        anomalies du modèle."""
        model = _keep_types(model, home_model.load(request.app.state.graph))
        _save_home(request.app.state.graph, model)
        saved = home_model.load(request.app.state.graph)
        ingestor: Ingestor | None = request.app.state.ingestor
        if ingestor:
            await ingestor.reload(saved)  # l'ingestion suit aussitôt les entités retenues
        return saved

    @app.get("/api/home/types")
    def get_types(request: Request) -> DeviceTypes:
        """Types de la bibliothèque qui acceptent des sous-types, et types propres (lot 2t.1)."""
        saved = home_model.load(request.app.state.graph)
        library = [
            LibraryType(
                kind=kind,
                behaviors=list(configuration.BEHAVIORS[kind]),
                roles=list(home_model.EXPECTED_ROLES[kind]),
                subtypes=kind in home_model.TYPE_PARENTS,
            )
            for kind in DeviceKind
        ]
        return DeviceTypes(
            parents=list(home_model.TYPE_PARENTS), types=saved.types, library=library
        )

    @app.post("/api/home/types")
    def create_type(request: Request, wanted: NewDeviceType) -> home_model.DeviceType:
        """Crée un type propre, sous-type d'un type de la bibliothèque ; 422 sinon."""
        graph = request.app.state.graph
        saved = home_model.load(graph)
        created = home_model.DeviceType(
            key=home_model.type_key(wanted.name, saved.types),
            name=wanted.name.strip(),
            parent=wanted.parent,
        )
        _save_home(graph, saved.model_copy(update={"types": [*saved.types, created]}))
        return created

    @app.patch("/api/home/types/{key}")
    def rename_type(request: Request, key: str, wanted: TypeName) -> home_model.DeviceType:
        """Renomme un type propre (sa clé ne change pas) ; 404 s'il n'existe pas."""
        graph = request.app.state.graph
        saved = home_model.load(graph)
        if not any(t.key == key for t in saved.types):
            raise HTTPException(status_code=404, detail="Type inconnu")
        types = [
            t.model_copy(update={"name": wanted.name.strip()}) if t.key == key else t
            for t in saved.types
        ]
        _save_home(graph, saved.model_copy(update={"types": types}))
        return next(t for t in types if t.key == key)

    @app.delete("/api/home/types/{key}", status_code=204)
    def delete_type(request: Request, key: str) -> None:
        """Supprime un type propre ; 404 s'il n'existe pas, 409 si un équipement l'a."""
        graph = request.app.state.graph
        saved = home_model.load(graph)
        if not any(t.key == key for t in saved.types):
            raise HTTPException(status_code=404, detail="Type inconnu")
        users = [d.key for d in saved.devices if d.custom_type == key]
        if users:
            raise HTTPException(status_code=409, detail={"code": "type_in_use", "devices": users})
        types = [t for t in saved.types if t.key != key]
        _save_home(graph, saved.model_copy(update={"types": types}))

    @app.get("/api/configuration")
    def get_configuration(request: Request) -> configuration.Configuration:
        """Réglages de chaque équipement du modèle de la maison (``default`` : rien d'enregistré,
        réglages par défaut de son type)."""
        graph = request.app.state.graph
        return configuration.effective(home_model.load(graph), configuration.load(graph))

    @app.get("/api/configuration/tariff-proposal")
    def tariff_proposal(request: Request) -> Tariff | None:
        """Tarif proposé d'après les prix du tableau Énergie de HA (``null`` sans prix déclaré) ;
        503 sans HA connecté."""
        client = connected_client(request)
        grid = energy_sources(client.energy_preferences).grid
        return propose_tariff(
            grid.import_price,
            grid.import_price_entity,
            grid.export_price,
            grid.export_price_entity,
        )

    @app.get("/api/configuration/task-rules-proposal")
    async def task_rules_proposal(request: Request) -> list[TaskRules]:
        """Règles reprises des descriptions JSON des tâches de la liste de HA (récurrence,
        « démarre après »), à valider dans l'onglet Maison ; 503 sans HA connecté."""
        client = connected_client(request)
        settings = load_planning_settings(request.app.state.database)
        due, waiting = await read_tasks(client, settings.todo_entity)
        return rules_from_tasks([*due, *waiting], home_model.load(request.app.state.graph))

    @app.post("/api/configuration/validate")
    def validate_configuration(
        request: Request, proposed: configuration.Configuration
    ) -> ConfigurationCheck:
        """Anomalies d'une configuration, sans l'enregistrer."""
        home = home_model.load(request.app.state.graph)
        return ConfigurationCheck(issues=configuration.validate(home, proposed))

    @app.get("/api/profiles")
    def list_profiles() -> list[dict[str, str]]:
        """Profils d'exemple (lot 3.8) : nom et description."""
        return [
            {"name": name, "description": profiles.document(name)["description"]}
            for name in profiles.names()
        ]

    @app.get("/api/profiles/{name}")
    def get_profile(name: str) -> dict[str, Any]:
        """Fichier d'un profil d'exemple, à importer (``/api/configuration/import``)."""
        try:
            return profiles.document(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Profil inconnu") from None

    @app.get("/api/configuration/export")
    def export_home(request: Request) -> JSONResponse:
        """Modèle de la maison et configuration en un fichier JSON versionné (lot 3.8)."""
        graph = request.app.state.graph
        found = exchange.export(home_model.load(graph), configuration.load(graph))
        return JSONResponse(
            found.model_dump(mode="json"),
            headers={"Content-Disposition": 'attachment; filename="wattslot-home.json"'},
        )

    @app.get("/api/configuration/export.ttl")
    def export_turtle(request: Request) -> Response:
        """Graphes de la maison et de sa configuration en Turtle, pour l'ontologie."""
        graph = request.app.state.graph
        body = graph.turtle(GRAPH_HOME) + b"\n" + graph.turtle(GRAPH_CONFIGURATION)
        return Response(
            body,
            media_type="text/turtle",
            headers={"Content-Disposition": 'attachment; filename="wattslot-home.ttl"'},
        )

    @app.post("/api/configuration/import")
    async def import_home(
        request: Request, document: Annotated[Any, Body()], dry_run: bool = False
    ) -> exchange.ImportCheck:
        """Vérifie le fichier ; sans ``dry_run`` et sans anomalie, remplace le modèle de la maison
        et la configuration. 422 avec les anomalies sinon."""
        client: HomeAssistantClient | None = request.app.state.home_assistant
        connected = client is not None and client.status.state is ConnectionState.CONNECTED
        known = list(client.snapshot.states) if client is not None and connected else None
        found, result = exchange.check(document, known)
        if found is None:
            if dry_run:
                return result
            raise HTTPException(status_code=422, detail=result.model_dump(mode="json"))
        if dry_run:
            return result
        graph = request.app.state.graph
        home_model.save(graph, found.home)
        configuration.save(graph, found.configuration)
        ingestor: Ingestor | None = request.app.state.ingestor
        if ingestor:
            await ingestor.reload(home_model.load(graph))
        return result.model_copy(update={"applied": True})

    @app.put("/api/configuration")
    def put_configuration(
        request: Request, proposed: configuration.Configuration
    ) -> configuration.Configuration:
        """Enregistre la configuration ; 422 avec les anomalies si elle n'est pas valide."""
        graph = request.app.state.graph
        home = home_model.load(graph)
        issues = configuration.validate(home, proposed)
        if issues:
            raise HTTPException(status_code=422, detail=[i.model_dump() for i in issues])
        configuration.save(graph, proposed)
        return configuration.effective(home, configuration.load(graph))

    def template_of(key: str) -> templates.Template:
        try:
            return templates.load(key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Modèle inconnu") from None

    @app.get("/api/templates")
    def get_templates(request: Request) -> list[TemplateSummary]:
        """Modèles prêts à l'emploi (lot 4.3), avec les équipements de la maison que chacun
        réglerait ; le modèle Tempo d'abord si HA a une entité Tempo."""
        graph = request.app.state.graph
        home = home_model.load(graph)
        client: HomeAssistantClient | None = request.app.state.home_assistant
        tempo = client is not None and any("tempo" in e for e in client.snapshot.states)
        found = [
            TemplateSummary(
                key=t.key,
                name=t.name,
                description=t.description,
                tariff_kind=t.tariff.kind.value,
                devices=[d.key for d in home.devices if templates.device_settings(t, home, d)],
            )
            for t in templates.all_templates()
        ]
        return sorted(found, key=lambda t: not (tempo and t.key == "tempo"))

    @app.post("/api/templates/{key}/preview")
    def preview_template(
        request: Request, key: str, entities: TariffEntities | None = None
    ) -> Preview:
        """Ce que le modèle changerait, sans rien enregistrer ; ``issues`` non vide s'il
        manque quelque chose (entité de la couleur Tempo, du prix dynamique)."""
        graph = request.app.state.graph
        return templates.preview(
            template_of(key), home_model.load(graph), configuration.load(graph), entities
        )

    @app.post("/api/templates/{key}/apply")
    def apply_template(
        request: Request, key: str, entities: TariffEntities | None = None
    ) -> configuration.Configuration:
        """Applique le modèle à la configuration ; 422 avec les anomalies sinon."""
        graph = request.app.state.graph
        home = home_model.load(graph)
        result = templates.apply(template_of(key), home, configuration.load(graph), entities)
        issues = configuration.validate(home, result)
        if issues:
            raise HTTPException(status_code=422, detail=[i.model_dump() for i in issues])
        configuration.save(graph, result)
        return configuration.effective(home, configuration.load(graph))

    @app.get("/api/ingestion")
    def ingestion(request: Request) -> IngestionStatus:
        """État de l'ingestion : entités suivies, derniers relevés, écritures."""
        ingestor: Ingestor | None = request.app.state.ingestor
        if ingestor is None:
            return IngestionStatus(running=False, entities=[], received=0, written=0, pending=0)
        return ingestor.status()

    @app.get("/api/aggregation")
    def aggregation(request: Request) -> AggregationStatus:
        """État de l'agrégation : périodes calculées, agrégats écrits, dernière erreur."""
        aggregator: Aggregator | None = request.app.state.aggregator
        return aggregator.status() if aggregator else AggregationStatus(running=False)

    @app.get("/api/planning/history")
    async def planning_history(request: Request, day: date | None = None) -> PlanningHistory:
        """Entrées du calcul tirées de l'historique, pour un jour (aujourd'hui par défaut) :
        ligne de base, meilleure production, historique récent (comparaison avec la v1)."""
        aggregator: Aggregator | None = request.app.state.aggregator
        if aggregator is None:
            raise HTTPException(status_code=503, detail="Agrégation inactive (HA non configuré)")
        zone = request.app.state.raw.zone
        today = datetime.now(UTC).astimezone(zone).date()
        model = home_model.load(request.app.state.graph)

        def compute() -> PlanningHistory:
            cycle_journal = CycleJournal(
                request.app.state.database, request.app.state.raw, aggregator
            )
            profiles = {
                appliance.name: journal.profile_summary(cycle_journal.profile(appliance, today))
                | {"sources": cycle_journal.sources(appliance, today)}
                for appliance in journal.appliances(model)
            }
            return PlanningHistory(
                day=day or today,
                baseline_kwh=past.baseline(model, aggregator, day or today, today, zone),
                best_production=past.best_production(model, aggregator, today, zone),
                recent_history=past.recent_history(model, aggregator, today, zone),
                battery_efficiencies=past.battery_efficiencies(model, aggregator, today, zone),
                cycle_profiles=profiles,
                real_cycles=journal.real_cycles(model, request.app.state.raw, datetime.now(UTC)),
            )

        return await asyncio.to_thread(compute)

    @app.get("/api/settings/planning")
    def get_planning_settings(request: Request) -> PlanningSettings:
        """Réglages du calcul : objectif, liste de tâches, entités de prévision de repli,
        puissances de la batterie."""
        return load_planning_settings(request.app.state.database)

    @app.get("/api/settings/choices")
    async def get_settings_choices(request: Request) -> SettingsChoices:
        """Choix proposés par le formulaire des réglages (lot 4.2) : listes de tâches, services
        de notification, entités de prévision de repli ; listes vides sans HA connecté."""
        return await settings_choices(request.app.state.home_assistant)

    @app.put("/api/settings/planning")
    def put_planning_settings(request: Request, settings: PlanningSettings) -> PlanningSettings:
        save_planning_settings(request.app.state.database, settings)
        return load_planning_settings(request.app.state.database)

    @app.get("/api/settings/currency")
    def get_currency() -> currency.CurrencyState:
        """Devise de la maison (lot 7.3) : réglage, devise de HA, devise retenue."""
        return currency.state()

    @app.put("/api/settings/currency")
    def put_currency(request: Request, setting: currency.CurrencySetting) -> currency.CurrencyState:
        currency.save(request.app.state.database, setting)
        return currency.state()

    @app.get("/api/planning/input")
    async def planning_input(request: Request, day: date | None = None) -> dict[str, Any]:
        """Entrée du calcul assemblée pour un jour (aujourd'hui par défaut), au format de la v1 :
        comparaison croisée avec les entrées capturées de la v1."""
        client = connected_client(request)
        aggregator: Aggregator | None = request.app.state.aggregator
        if aggregator is None:
            raise HTTPException(status_code=503, detail="Agrégation inactive")
        state = request.app.state
        now = datetime.now(UTC)
        target = day or now.astimezone(state.raw.zone).date()
        cycle_journal = CycleJournal(state.database, state.raw, aggregator)
        settings_now = configuration.load(state.graph)
        model_now = home_model.load(state.graph)
        try:
            data = await build_input(
                target,
                now,
                client,
                model_now,
                aggregator,
                state.raw,
                cycle_journal,
                load_planning_settings(state.database),
                forecasts=Forecasts(
                    client,
                    state.raw.zone,
                    load_planning_settings(state.database),
                    open_meteo.fallback_for(state.database, settings_now, client),
                    has_production(model_now),
                ),
                configuration=settings_now,
                database=state.database,
            )
        except ForecastUnavailable as exc:
            raise HTTPException(
                status_code=409, detail=f"Aucune prévision solaire pour le {exc}"
            ) from exc
        return to_v1(data)

    @app.post("/api/planning/run")
    async def planning_run(request: Request) -> RunReport:
        """Calcule le plan du jour, puis demain et l'horizon (un calcul à la fois)."""
        client = connected_client(request)
        state = request.app.state
        if state.aggregator is None:
            raise HTTPException(status_code=503, detail="Agrégation inactive")
        context = Context(
            client=client,
            model=home_model.load(state.graph),
            reader=state.aggregator,
            raw=state.raw,
            database=state.database,
            settings=load_planning_settings(state.database),
            configuration=configuration.load(state.graph),
            data_dir=settings.data_dir,
        )
        async with state.planning_lock:
            try:
                return await run(context, datetime.now(UTC), manual=True)
            except ForecastUnavailable as exc:
                raise HTTPException(
                    status_code=409, detail=f"Aucune prévision solaire pour le {exc}"
                ) from exc

    @app.post("/api/planning/actual")
    async def planning_actual(request: Request) -> dict[str, Any]:
        """Bouton « Rafraîchir » : données réelles du jour relues sur le brut, gardées dans le
        plan du jour. Si ce plan porte encore sur la veille, calcul complet (bascule)."""
        state = request.app.state
        if state.aggregator is None:
            raise HTTPException(status_code=503, detail="Agrégation inactive")
        model = home_model.load(state.graph)
        now = datetime.now(UTC)
        async with state.planning_lock:
            found = await asyncio.to_thread(
                refresh_actual,
                model,
                state.raw,
                state.database,
                now,
                configuration.load(state.graph),
            )
            if found is not None:
                return found
            context = Context(
                client=connected_client(request),
                model=model,
                reader=state.aggregator,
                raw=state.raw,
                database=state.database,
                settings=load_planning_settings(state.database),
                configuration=configuration.load(state.graph),
                data_dir=settings.data_dir,
            )
            try:
                await run(context, now, manual=True)
            except ForecastUnavailable as exc:
                raise HTTPException(
                    status_code=409, detail=f"Aucune prévision solaire pour le {exc}"
                ) from exc
        plan = stored_plan(state.database, "today")
        return (plan or {}).get("donnees_reelles_cache") or {}

    @app.post("/api/planning/notify")
    async def planning_notify(request: Request) -> dict[str, str]:
        """Notification d'essai de la recommandation du plan du jour (gardée pour l'interface
        d'avant le lot 5.6). 409 sans service choisi (« no_notify_service ») ni plan du jour
        (« no_plan ») : codes traduits par l'interface."""
        sent = await _test_notification(request, "recommendation")
        return {"service": sent.service, "message": sent.message}

    @app.get("/api/settings/notifications")
    def get_notification_settings(request: Request) -> notifications.NotificationSettings:
        """Notifications activables (lot 5.6) : appareil commun, langue, et pour chacune
        activation, appareil, heures de silence ; la recommandation a aussi son rythme."""
        return notifications.load(request.app.state.database)

    @app.put("/api/settings/notifications")
    def put_notification_settings(
        request: Request, settings: notifications.NotificationSettings
    ) -> notifications.NotificationSettings:
        notifications.save(request.app.state.database, settings)
        return notifications.load(request.app.state.database)

    @app.post("/api/notifications/{kind}/test")
    async def notification_test(request: Request, kind: notifications.Kind) -> notifications.Sent:
        """Envoi d'essai d'une notification, tout de suite, sans heures de silence ni rythme."""
        return await _test_notification(request, kind)

    async def _test_notification(request: Request, kind: notifications.Kind) -> notifications.Sent:
        client = connected_client(request)
        try:
            return await notifications.send_test(
                client, request.app.state.database, kind, zone=request.app.state.raw.zone
            )
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/forecast/comparison")
    async def forecast_comparison(request: Request) -> open_meteo.Comparison:
        """Prévision Open-Meteo des 7 derniers jours comparée à la production mesurée (lot 4.4) ;
        ``available`` faux sans panneaux décrits, sans position de HA ou sans réponse."""
        state = request.app.state
        settings_now = configuration.load(state.graph)
        if not open_meteo.installations(settings_now):
            return open_meteo.Comparison(available=False, reason="no_panels")
        source = open_meteo.fallback_for(state.database, settings_now, state.home_assistant)
        if source is None or state.aggregator is None:
            return open_meteo.Comparison(available=False, reason="no_position")
        today = datetime.now(UTC).astimezone(state.raw.zone).date()
        model = home_model.load(state.graph)
        return await open_meteo.compare(source, model, state.aggregator, today, state.raw.zone)

    @app.get("/api/planning/status")
    def planning_status(request: Request) -> SchedulerStatus:
        """Planificateur des calculs : prochain calcul, dernier bilan, dernière erreur."""
        scheduler: PlanningScheduler | None = request.app.state.scheduler
        if scheduler is None:
            return SchedulerStatus(running=False, enabled=False)
        return scheduler.status()

    @app.get("/api/planning/plan")
    def planning_plan(
        request: Request, view: str = Query("today", pattern="^(today|yesterday|tomorrow|horizon)$")
    ) -> dict[str, Any]:
        """Plan gardé en base, au format de la v1 : ``today``, ``yesterday``, ``tomorrow``,
        ``horizon``."""
        assert view in PLAN_KINDS
        found = stored_plan(request.app.state.database, view)
        if found is None:
            raise HTTPException(status_code=404, detail="Aucun plan calculé")
        return found

    @app.get("/api/aggregates")
    def aggregates(
        request: Request,
        entity_id: str,
        start: datetime,
        end: datetime | None = None,
        period: str = Query("PT1H", pattern="^(PT15M|PT1H)$"),
    ) -> list[Aggregate]:
        """Agrégats d'une entité suivie, de ``start`` à ``end`` (un jour par défaut)."""
        if start.tzinfo is None or (end is not None and end.tzinfo is None):
            raise HTTPException(status_code=422, detail="Heures avec fuseau attendues")
        aggregator: Aggregator | None = request.app.state.aggregator
        if aggregator is None or period not in PERIODS:
            return []
        return aggregator.read(entity_id, period, start, end or start + timedelta(days=1))

    @app.get("/api/setup")
    async def get_setup(request: Request) -> Setup:
        """Mise en route (lot 4.1) : étapes vers un premier plan, avec leur état."""
        state = request.app.state
        return await setup_status(
            state.home_assistant, state.graph, state.database, state.aggregator, state.raw.zone
        )

    @app.get("/api/diagnostic")
    async def get_diagnostic(request: Request) -> Diagnostic:
        """Tout l'état de l'application en une réponse : la page de diagnostic."""
        state = request.app.state
        return await asyncio.to_thread(
            diagnostic,
            state.home_assistant,
            state.ingestor,
            state.raw,
            state.aggregator,
            state.maintenance,
            state.scheduler,
        )

    async def current_problems(request: Request) -> tuple[Diagnostic, list[Problem]]:
        return await current_problems_of(request.app.state)

    async def current_problems_of(state: Any) -> tuple[Diagnostic, list[Problem]]:
        found = await asyncio.to_thread(
            diagnostic,
            state.home_assistant,
            state.ingestor,
            state.raw,
            state.aggregator,
            state.maintenance,
            state.scheduler,
        )
        setup = await setup_status(
            state.home_assistant, state.graph, state.database, state.aggregator, state.raw.zone
        )
        home = home_model.load(state.graph)
        problems = collect(
            setup, found, home, configuration.load(state.graph), state.home_assistant
        )
        return found, problems

    @app.get("/api/diagnostic/problems")
    async def get_problems(request: Request) -> list[Problem]:
        """Ce qui ne va pas (lot 4.8), les plus graves d'abord, avec le geste à faire."""
        return (await current_problems(request))[1]

    @app.get("/api/diagnostic/report")
    async def get_report(request: Request) -> dict[str, Any]:
        """Rapport anonymisé à joindre à un ticket (lot 4.8) : ni identifiant d'entité, ni nom
        d'équipement, ni position."""
        state = request.app.state
        found, problems = await current_problems(request)
        client: HomeAssistantClient | None = state.home_assistant
        return report.build(
            mode=settings.mode.value,
            ha_version=client.status.version if client else None,
            ha_state=(client.status.state if client else ConnectionState.NOT_CONFIGURED).value,
            diagnostic=found,
            problems=problems,
            home=home_model.load(state.graph),
            saved=configuration.load(state.graph),
            settings=load_planning_settings(state.database),
        )

    def requestable(request: Request) -> list[RequestableDevice]:
        graph = request.app.state.graph
        found = cycle_appliances(home_model.load(graph), configuration.load(graph))
        return [RequestableDevice(key=a.key, name=a.name) for a in found]

    @app.get("/api/requests/devices")
    def request_devices(request: Request) -> list[RequestableDevice]:
        """Équipements qu'on peut demander (lot 4.5) : cycles à démarrer et besoins d'énergie."""
        return requestable(request)

    @app.get("/api/requests")
    def get_requests(request: Request) -> list[user_requests.UserRequest]:
        """Demandes ouvertes, puis celles closes depuis 7 jours."""
        return user_requests.recent(request.app.state.database, datetime.now(UTC))

    @app.post("/api/requests")
    def post_request(request: Request, asked: NewRequest) -> user_requests.UserRequest:
        """Demande pour un équipement ; une demande déjà ouverte pour lui change de date. 422
        pour un équipement qu'on ne peut pas demander."""
        if asked.device not in {d.key for d in requestable(request)}:
            raise HTTPException(status_code=422, detail="device_not_requestable")
        return user_requests.ask(
            request.app.state.database, asked.device, asked.latest, datetime.now(UTC)
        )

    def close_request(
        request: Request, request_id: int, status: user_requests.Status
    ) -> user_requests.UserRequest:
        found = user_requests.close(
            request.app.state.database, request_id, status, datetime.now(UTC)
        )
        if found is None:
            raise HTTPException(status_code=404, detail="Demande inconnue")
        return found

    @app.post("/api/requests/{request_id}/done")
    def request_done(request: Request, request_id: int) -> user_requests.UserRequest:
        return close_request(request, request_id, user_requests.Status.DONE)

    @app.delete("/api/requests/{request_id}")
    def cancel_request(request: Request, request_id: int) -> user_requests.UserRequest:
        return close_request(request, request_id, user_requests.Status.CANCELLED)

    @app.get("/api/settings/retention")
    def get_retention(request: Request) -> Retention:
        """Durées de conservation (jours) : brut, quarts d'heure, heures (sans limite : null)."""
        return load_retention(request.app.state.database)

    @app.put("/api/settings/retention")
    def put_retention(request: Request, retention: Retention) -> Retention:
        """Appliquées à la prochaine maintenance."""
        save_retention(request.app.state.database, retention)
        return load_retention(request.app.state.database)

    @app.get("/api/maintenance")
    def maintenance_status(request: Request) -> MaintenanceStatus:
        """Maintenance nocturne : prochaine exécution, dernier bilan, volumes sur disque."""
        maintenance: Maintenance | None = request.app.state.maintenance
        if maintenance is None:
            raise HTTPException(status_code=503, detail="Maintenance inactive (HA non configuré)")
        return maintenance.status()

    @app.post("/api/maintenance/run")
    async def run_maintenance(request: Request) -> MaintenanceRun:
        """Lance la maintenance tout de suite (attend sa fin)."""
        maintenance: Maintenance | None = request.app.state.maintenance
        if maintenance is None:
            raise HTTPException(status_code=503, detail="Maintenance inactive (HA non configuré)")
        return await maintenance.run()

    # --- Sauvegarde à chaud de l'extension (lot 6t.3, ``backup.py``) -----------------------

    def local_only(request: Request) -> None:
        """Commandes ``backup_pre`` et ``backup_post``, lancées dans le conteneur : refusées à
        toute autre adresse, ingress compris."""
        if request.client is None or request.client.host not in backup.LOCAL_ADDRESSES:
            raise HTTPException(status_code=403, detail="Réservé à la machine elle-même")

    @app.post("/api/backup/prepare", dependencies=[Depends(local_only)])
    async def backup_prepare(request: Request) -> dict[str, str]:
        """Fige une copie de la base et du graphe dans ``backup/`` (avant la copie de HA)."""
        state = request.app.state
        target = await asyncio.to_thread(
            backup.prepare, settings.data_dir, state.database, state.graph
        )
        logger.info("Sauvegarde : copie figée dans %s", target)
        return {"snapshot": str(target)}

    @app.post("/api/backup/finish", dependencies=[Depends(local_only)])
    async def backup_finish() -> dict[str, bool]:
        """Supprime la copie (après la copie de HA)."""
        await asyncio.to_thread(backup.finish, settings.data_dir)
        return {"removed": True}

    # --- Connexion à HA en mode autonome (lot 4.6) ---------------------------------------
    logins = connection.PendingLogins()

    def restart_soon() -> None:
        """Arrêt propre peu après la réponse : Docker relance l'application (``restart:
        unless-stopped``), qui démarre alors avec la nouvelle connexion."""

        async def stop() -> None:
            await asyncio.sleep(1)
            os.kill(os.getpid(), signal.SIGTERM)

        app.state.restart_task = asyncio.get_running_loop().create_task(stop())

    app.state.restart = restart_soon

    def editable() -> None:
        if settings.mode is RunMode.ADDON:
            raise HTTPException(status_code=409, detail="addon_mode")
        if settings.connection_source == "env":
            raise HTTPException(status_code=409, detail="set_by_environment")

    def url_of(value: str) -> str:
        try:
            return connection.normalize_url(value)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid_url") from None

    @app.get("/api/connection")
    def get_connection(request: Request) -> ConnectionInfo:
        """Connexion à HA : d'où elle vient, adresse, méthode et état ; jamais de jeton."""
        client: HomeAssistantClient | None = request.app.state.home_assistant
        stored = (
            connection.load(settings.data_dir) if settings.connection_source == "saved" else None
        )
        return ConnectionInfo(
            mode=settings.mode,
            source=settings.connection_source,
            url=stored.url if stored else settings.suggested_url,
            method=stored.method if stored else None,
            state=client.status.state if client else ConnectionState.NOT_CONFIGURED,
            error=client.status.error if client else None,
        )

    @app.post("/api/connection/token")
    async def connect_with_token(request: Request, asked: TokenLogin) -> dict[str, bool]:
        """Jeton longue durée saisi, vérifié auprès de HA puis enregistré ; l'application
        redémarre. 400 ``token_refused`` ou ``unreachable``."""
        editable()
        url = url_of(asked.url)
        try:
            await connection.check_token(url, asked.token.strip(), get=connection.get_status)
        except connection.ConnectionFailed as exc:
            refused = str(exc).startswith("HTTP")
            raise HTTPException(
                status_code=400, detail="token_refused" if refused else "unreachable"
            ) from exc
        stored = connection.StoredConnection(url=url, method="token", token=asked.token.strip())
        connection.save(settings.data_dir, stored)
        request.app.state.restart()
        return {"restarting": True}

    @app.post("/api/connection/oauth")
    def connect_with_oauth(asked: OAuthLogin) -> dict[str, str]:
        """Adresse de la page de connexion de HA pour « Se connecter avec Home Assistant »."""
        editable()
        url, client_id = url_of(asked.url), url_of(asked.client_id)
        return {"authorize_url": logins.start(url, client_id)}

    @app.get("/auth/callback")
    async def oauth_callback(request: Request, state: str = "", code: str = "") -> RedirectResponse:
        """Retour de HA : code échangé contre les jetons, enregistrés ; retour à l'application."""
        editable()
        found = logins.take(state)
        if found is None or not code:
            return RedirectResponse("../?connection=expired", status_code=303)
        url, client_id = found
        try:
            stored = await connection.exchange_code(url, code, client_id, post=connection.post_form)
        except connection.ConnectionFailed:
            return RedirectResponse("../?connection=failed", status_code=303)
        connection.save(settings.data_dir, stored)
        request.app.state.restart()
        return RedirectResponse("../?connection=ok", status_code=303)

    @app.delete("/api/connection")
    async def disconnect(request: Request) -> dict[str, bool]:
        """Déconnexion : jeton de rafraîchissement révoqué auprès de HA, connexion oubliée ;
        l'application redémarre."""
        editable()
        stored = connection.load(settings.data_dir)
        if stored is None:
            raise HTTPException(status_code=404, detail="not_connected")
        with contextlib.suppress(connection.ConnectionFailed):
            await connection.revoke(stored, post=connection.post_form)
        connection.delete(settings.data_dir)
        request.app.state.restart()
        return {"restarting": True}

    # Vues du nouveau dashboard (phase 5) et leur disposition (lot 5.5).
    app.include_router(views_routes.router)
    app.include_router(views_layout.router)

    # Interface compilée (image Docker) : servie à la racine, après les routes de l'API.
    if settings.static_dir and settings.static_dir.is_dir():
        app.mount("/", InterfaceFiles(directory=settings.static_dir, html=True), name="interface")

    return app


app = create_app()
