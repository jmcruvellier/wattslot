"""Démonstration des captures (lot 7.2) : données calculées par le serveur, heure figée à 14 h 30.

``generate`` remplit un dossier de données comme l'aurait fait l'application connectée à la
maison synthétique de ``demo_home`` depuis 31 jours :

1. un faux Home Assistant (API WebSocket) expose les capteurs de la maison, son tableau Énergie
   et une prévision solaire ; la maison proposée par la détection est enregistrée (noms dans la
   langue des captures), avec le modèle « heures creuses », la batterie et une notification ;
2. la maison est simulée minute par minute : relevés bruts écrits, agrégats calculés par
   l'agrégation de l'application, brut au-delà de 3 jours supprimé (conservation par défaut) ;
3. depuis minuit la veille, le vrai calcul (``planning.runner.run``) tourne à chaque
   heure à la minute 59, comme le planificateur ; le foyer lance les appareils demandés à l'heure
   que le plan leur donne ; à 14 h 30, les données réelles du jour sont relues.

``serve`` lance l'application sur ce dossier, connectée au faux HA, avec l'heure de
l'application figée à 14 h 30 du jour J (``datetime.now`` des modules de ``wattslot``).

Depuis ``dev/``, avec l'environnement du serveur (``pip install -e app/backend``) ::

    python -m tools.demo generate --language en --data <dossier>
    python -m tools.demo serve --data <dossier> --port 8100
"""

import argparse
import asyncio
import json
import logging
import shutil
import sys
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from tools import demo_home as house_data
from tools.demo_home import (
    APPLIANCES,
    BATTERY_CAPACITY,
    BATTERY_CHARGE,
    BATTERY_DISCHARGE,
    BATTERY_LEVEL,
    CAPACITY_KWH,
    DAY,
    DISHWASHER,
    DRYER,
    GRID_EXPORT,
    GRID_IMPORT,
    NAMES,
    NOW,
    SOLAR_ENERGY,
    SOLAR_POWER,
    WASHING_MACHINE,
    WATER_HEATER,
    ZONE,
    House,
    energy_entity,
    power_entity,
)

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "app" / "frontend" / "dist"
TOKEN = "demo-token"
HA_VERSION = "2026.6.1"
NOTIFY = "mobile_app_phone"
# Calculs horaires simulés depuis minuit la veille (vue Hier), jusqu'à 13 h 59 le jour J.
WINDOW = datetime.combine(DAY - timedelta(days=1), datetime.min.time(), ZONE)
RAW_DAYS = 3  # conservation du brut par défaut (``maintenance.Retention``)

# Demandes du foyer dans l'application : (heure, appareil, au plus tard ; aucun : dès que
# possible). Lave-linge et sèche-linge sans date : « après le lave-linge » ne lie que des
# demandes sans date (``assemble._ordered``).
_D = datetime.combine(DAY, datetime.min.time(), ZONE)
REQUESTS: tuple[tuple[datetime, str, date | None], ...] = (
    (WINDOW + timedelta(hours=7, minutes=20), DISHWASHER, DAY - timedelta(days=1)),
    (_D + timedelta(hours=7, minutes=40), WASHING_MACHINE, None),
    (_D + timedelta(hours=7, minutes=41), DRYER, None),
    (_D + timedelta(hours=9, minutes=10), DISHWASHER, DAY),
)

logger = logging.getLogger("demo")


# --- Heure figée ----------------------------------------------------------------------------


class Clock:
    """Heure de l'application pendant la génération (avancée par la simulation) et le service."""

    moment: datetime = NOW


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> "FrozenDatetime":  # type: ignore[override]
        local = Clock.moment.astimezone(tz if tz is not None else ZONE)
        moment = local if tz is not None else local.replace(tzinfo=None)
        return cls.combine(moment.date(), moment.timetz())

    @classmethod
    def utcnow(cls) -> "FrozenDatetime":  # type: ignore[override]
        return cls.now(UTC).replace(tzinfo=None)


def freeze_time() -> None:
    """Remplace ``datetime`` dans les modules de ``wattslot`` déjà importés."""
    for name, module in list(sys.modules.items()):
        if (name == "wattslot" or name.startswith("wattslot.")) and getattr(
            module, "datetime", None
        ) is datetime:
            module.datetime = FrozenDatetime  # type: ignore[attr-defined]


def import_application() -> None:
    """Importe toute l'application (pour que ``freeze_time`` atteigne chaque module)."""
    import wattslot.main
    import wattslot.planning.runner  # noqa: F401


# --- Faux Home Assistant ------------------------------------------------------------------


def _sensor(entity_id: str, value: float, name: str, kind: str) -> dict[str, Any]:
    units = {
        "energy": ("kWh", "energy", "total_increasing"),
        "power": ("W", "power", "measurement"),
        "battery": ("%", "battery", "measurement"),
        "storage": ("kWh", "energy_storage", None),
    }
    unit, device_class, state_class = units[kind]
    attributes: dict[str, Any] = {
        "friendly_name": name,
        "unit_of_measurement": unit,
        "device_class": device_class,
    }
    if state_class:
        attributes["state_class"] = state_class
    return {"entity_id": entity_id, "state": str(value), "attributes": attributes}


SENSOR_LABELS = {
    "en": {
        "power": "power",
        "energy": "energy",
        "import": "Grid import",
        "export": "Grid export",
        "charge": "charged",
        "discharge": "discharged",
        "level": "level",
        "capacity": "capacity",
    },
    "fr": {
        "power": "puissance",
        "energy": "énergie",
        "import": "Soutirage réseau",
        "export": "Injection réseau",
        "charge": "chargée",
        "discharge": "déchargée",
        "level": "niveau",
        "capacity": "capacité",
    },
}

DEVICE_OF: dict[str, str] = {
    SOLAR_POWER: "solar",
    SOLAR_ENERGY: "solar",
    GRID_IMPORT: "grid",
    GRID_EXPORT: "grid",
    BATTERY_CHARGE: "battery",
    BATTERY_DISCHARGE: "battery",
    BATTERY_LEVEL: "battery",
    BATTERY_CAPACITY: "battery",
    **{power_entity(a): a for a in APPLIANCES},
    **{energy_entity(a): a for a in APPLIANCES},
}


def ha_states(values: dict[str, float], language: str) -> list[dict[str, Any]]:
    """États de HA des capteurs de la maison, avec leurs attributs."""
    names, labels = NAMES[language], SENSOR_LABELS[language]
    found = [
        _sensor(SOLAR_POWER, values[SOLAR_POWER], f"{names['solar']} {labels['power']}", "power"),
        _sensor(
            SOLAR_ENERGY, values[SOLAR_ENERGY], f"{names['solar']} {labels['energy']}", "energy"
        ),
        _sensor(GRID_IMPORT, values[GRID_IMPORT], labels["import"], "energy"),
        _sensor(GRID_EXPORT, values[GRID_EXPORT], labels["export"], "energy"),
        _sensor(
            BATTERY_CHARGE,
            values[BATTERY_CHARGE],
            f"{names['battery']} {labels['charge']}",
            "energy",
        ),
        _sensor(
            BATTERY_DISCHARGE,
            values[BATTERY_DISCHARGE],
            f"{names['battery']} {labels['discharge']}",
            "energy",
        ),
        _sensor(
            BATTERY_LEVEL,
            values[BATTERY_LEVEL],
            f"{names['battery']} {labels['level']}",
            "battery",
        ),
        _sensor(
            BATTERY_CAPACITY, CAPACITY_KWH, f"{names['battery']} {labels['capacity']}", "storage"
        ),
    ]
    for appliance in APPLIANCES:
        for entity_id, kind in (
            (power_entity(appliance), "power"),
            (energy_entity(appliance), "energy"),
        ):
            found.append(
                _sensor(entity_id, values[entity_id], f"{names[appliance]} {labels[kind]}", kind)
            )
    return found


def registries(language: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(registre des entités, registre des appareils) de HA."""
    devices = sorted(set(DEVICE_OF.values()))
    return (
        [
            {"entity_id": entity_id, "device_id": f"demo-{device}", "platform": "demo"}
            for entity_id, device in sorted(DEVICE_OF.items())
        ],
        [{"id": f"demo-{device}", "name": NAMES[language][device]} for device in devices],
    )


ENERGY_PREFERENCES: dict[str, Any] = {
    "energy_sources": [
        {
            "type": "solar",
            "stat_energy_from": SOLAR_ENERGY,
            "stat_rate": SOLAR_POWER,
            "config_entry_solar_forecast": ["demo-forecast"],
        },
        {"type": "grid", "stat_energy_from": GRID_IMPORT, "stat_energy_to": GRID_EXPORT},
        {
            "type": "battery",
            "stat_energy_from": BATTERY_DISCHARGE,
            "stat_energy_to": BATTERY_CHARGE,
            "stat_soc": BATTERY_LEVEL,
        },
    ],
    "device_consumption": [
        {"stat_consumption": energy_entity(a), "stat_rate": power_entity(a)} for a in APPLIANCES
    ],
}


def solar_forecast() -> dict[str, Any]:
    """Prévision du tableau Énergie (``energy/solar_forecast``), de la veille à J+9."""
    wh_hours: dict[str, float] = {}
    for offset in range(-1, house_data.FORECAST_DAYS + 1):
        day = DAY + timedelta(days=offset)
        for hour, wh in house_data.forecast_wh(day).items():
            moment = datetime.combine(day, datetime.min.time(), ZONE) + timedelta(hours=hour)
            wh_hours[moment.astimezone(UTC).isoformat()] = wh
    return {"demo-forecast": {"wh_hours": wh_hours}}


class FakeHomeAssistant:
    """API WebSocket de HA réduite à ce que lit l'application ; états modifiables."""

    def __init__(self, language: str, values: dict[str, float]) -> None:
        self.language = language
        self.values = dict(values)
        self.forecast = solar_forecast()
        self.notifications: list[dict[str, Any]] = []

    def answer(self, message: dict[str, Any]) -> Any:
        kind = message["type"]
        entities, devices = registries(self.language)
        if kind == "get_config":
            return {
                "version": HA_VERSION,
                "time_zone": str(ZONE),
                "location_name": "Home" if self.language == "en" else "Maison",
                "unit_system": {"energy": "kWh"},
                "currency": "EUR",
                "language": self.language,
            }
        if kind == "get_states":
            return ha_states(self.values, self.language)
        if kind == "config/entity_registry/list":
            return entities
        if kind == "config/device_registry/list":
            return devices
        if kind == "energy/get_prefs":
            return ENERGY_PREFERENCES
        if kind == "energy/solar_forecast":
            return self.forecast
        if kind == "get_services":
            label = "Phone" if self.language == "en" else "Téléphone"
            return {"notify": {NOTIFY: {"name": f"{label}", "description": ""}}}
        if kind == "call_service":
            if message.get("domain") == "notify":
                self.notifications.append(message)
            return {"context": {"id": "demo"}, "response": {}}
        if kind in ("history/history_during_period", "recorder/statistics_during_period"):
            return {}
        logger.warning("Faux HA : commande sans réponse prévue %s", kind)
        return None

    async def handler(self, websocket: Any) -> None:
        await websocket.send(json.dumps({"type": "auth_required", "ha_version": HA_VERSION}))
        auth = json.loads(await websocket.recv())
        if auth.get("access_token") != TOKEN:
            await websocket.send(json.dumps({"type": "auth_invalid", "message": "Invalid token"}))
            return
        await websocket.send(json.dumps({"type": "auth_ok", "ha_version": HA_VERSION}))
        async for raw in websocket:
            message = json.loads(raw)
            reply: dict[str, Any] = {"id": message["id"], "type": "result", "success": True}
            if message["type"] == "subscribe_entities":
                await websocket.send(json.dumps(reply | {"result": None}))
                wanted = set(message.get("entity_ids") or [])
                changed = Clock.moment.timestamp()
                states = {
                    s["entity_id"]: {"s": s["state"], "a": s["attributes"], "lc": changed}
                    for s in ha_states(self.values, self.language)
                    if not wanted or s["entity_id"] in wanted
                }
                event = {"id": message["id"], "type": "event", "event": {"a": states}}
                await websocket.send(json.dumps(event))
                continue
            await websocket.send(json.dumps(reply | {"result": self.answer(message)}))

    @asynccontextmanager
    async def running(self, port: int = 0) -> Any:
        from websockets.asyncio.server import serve

        async with serve(self.handler, "127.0.0.1", port) as server:
            yield server.sockets[0].getsockname()[1]


# --- Génération -----------------------------------------------------------------------------


class _Targets:
    """Entités suivies, pour l'agrégation (l'ingestion de l'application n'est pas lancée)."""

    backfilling = False

    def __init__(self, targets: dict[str, Any]) -> None:
        self.targets = targets


def home_from_proposal(proposal: Any, language: str) -> Any:
    """Maison proposée par la détection, chaque équipement nommé dans la langue des captures."""
    from wattslot.detection import DeviceKind
    from wattslot.home_model import HomeDevice, HomeModel, HomeSensor

    by_kind = {
        DeviceKind.SOLAR: "solar",
        DeviceKind.GRID: "grid",
        DeviceKind.BATTERY: "battery",
        DeviceKind.WATER_HEATER: WATER_HEATER,
        DeviceKind.WASHING_MACHINE: WASHING_MACHINE,
        DeviceKind.DRYER: DRYER,
        DeviceKind.DISHWASHER: DISHWASHER,
    }
    return HomeModel(
        devices=[
            HomeDevice(
                key=device.key,
                kind=device.kind,
                name=NAMES[language][by_kind[device.kind]],
                capacity_kwh=device.capacity_kwh,
                sensors=[
                    HomeSensor(entity_id=s.entity_id, role=s.role, resets_daily=s.resets_daily)
                    for s in device.sensors
                    if not s.excluded
                ],
            )
            for device in proposal.devices
        ]
    )


def minutes(start: datetime, end: datetime) -> Iterator[datetime]:
    moment = start
    while moment < end:
        yield moment
        moment += timedelta(minutes=1)


def planned_starts(content: dict[str, Any], names: dict[str, str]) -> dict[str, datetime]:
    """Démarrages des appareils dans le plan du jour (clé → heure locale)."""
    from wattslot.planning.plan import Plan

    plan = Plan.from_v1(dict(content))
    day = date.fromisoformat(content["date_cible"])
    midnight = datetime.combine(day, datetime.min.time(), ZONE)
    found = {}
    for slot in plan.slots:
        key = names.get(slot.device)
        if key is None or slot.start_min is None:
            continue
        found[key] = midnight + timedelta(minutes=slot.start_min)
    return found


async def generate(data_dir: Path, language: str, quiet: bool = False) -> dict[str, Any]:
    """Dossier de données de la démonstration ; renvoie un résumé (plans, relevés)."""
    import_application()
    freeze_time()
    from wattslot import configuration, home_model, notifications, user_requests
    from wattslot.aggregation import Aggregator
    from wattslot.battery_settings import BatterySettings
    from wattslot.configuration import Automation, Behavior, DeviceSettings
    from wattslot.detection import DeviceKind, propose
    from wattslot.home_assistant import ConnectionState, HomeAssistantClient
    from wattslot.ingestion import targets
    from wattslot.planning import runner
    from wattslot.planning.sources import PlanningSettings, load_settings, save_settings
    from wattslot.planning.store import PlanStore
    from wattslot.runtime import HomeAssistantTarget
    from wattslot.solar_panels import PanelArray, SolarPanels
    from wattslot.storage.database import open_database
    from wattslot.storage.graph import GraphStore
    from wattslot.storage.raw import RawStores, Reading
    from wattslot.templates import apply
    from wattslot.templates import load as load_template
    from wattslot.time_constraints import ConstraintKind, TimeConstraint

    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    first = datetime.combine(
        DAY - timedelta(days=house_data.HISTORY_DAYS), datetime.min.time(), ZONE
    )
    window = WINDOW
    Clock.moment = first
    house = House()
    ha = FakeHomeAssistant(language, house.step(first - timedelta(minutes=1)))

    database = open_database(data_dir)
    graph = GraphStore(data_dir)
    home_model.load_vocabulary(graph)
    raw = RawStores(data_dir, str(ZONE))
    summary: dict[str, Any] = {"runs": 0, "readings": 0, "starts": []}

    async with ha.running() as port:
        client = HomeAssistantClient(
            HomeAssistantTarget(f"ws://127.0.0.1:{port}/api/websocket", TOKEN)
        )
        task = asyncio.create_task(client.run())
        try:
            async with asyncio.timeout(10):
                while client.status.state is not ConnectionState.CONNECTED:
                    await asyncio.sleep(0.02)

            home = home_from_proposal(propose(client.snapshot), language)
            home_model.save(graph, home)
            saved = apply(load_template("off_peak"), home, configuration.Configuration(), None)
            saved.battery = BatterySettings(
                charge_max_w=house_data.BATTERY_MAX_W,
                discharge_max_w=house_data.BATTERY_MAX_W,
                floor_percent=house_data.FLOOR_PERCENT,
            )
            # Lave-vaisselle pas avant 15 h (contrainte horaire) : la prochaine action à 14 h 30.
            for device in home.devices:
                found = saved.of(device.key)
                if found is not None and device.name == NAMES[language][DISHWASHER]:
                    found.constraints = [
                        TimeConstraint(kind=ConstraintKind.NOT_BEFORE, start_hour=15)
                    ]
            # Panneaux décrits : un toit de 4,5 kWc plein sud (sans position dans HA, la
            # prévision reste celle du tableau Énergie).
            solar = next(d for d in home.devices if d.kind is DeviceKind.SOLAR)
            saved.devices = [d for d in saved.devices if d.key != solar.key] + [
                DeviceSettings(
                    key=solar.key,
                    behavior=Behavior.PRODUCTION,
                    automation=Automation.INFORM,
                    panels=SolarPanels(arrays=[PanelArray(kwp=4.5)], inverter_kw=3.6),
                )
            ]
            issues = configuration.validate(home, configuration.effective(home, saved))
            if issues:
                raise RuntimeError(f"configuration de démonstration invalide : {issues}")
            configuration.save(graph, saved)
            save_settings(database, PlanningSettings())
            notifications.save(
                database,
                notifications.NotificationSettings(
                    service=f"notify.{NOTIFY}",
                    language=language,
                    recommendation=notifications.RecommendationRule(enabled=True),
                ),
            )
            model = home_model.load(graph)
            settings = configuration.load(graph)
            followed = targets(model)
            by_entity = {t.entity_id: t for t in followed.values()}
            aggregator = Aggregator(_Targets(followed), raw, graph, database, client)  # type: ignore[arg-type]
            names = {NAMES[language][a]: a for a in APPLIANCES}
            keys = {
                a: d.key for d in model.devices for a in APPLIANCES if d.name == NAMES[language][a]
            }
            pending_requests = list(REQUESTS)
            last: dict[str, float] = {}
            buffer: list[Reading] = []

            def flush() -> None:
                summary["readings"] += raw.write(buffer)
                buffer.clear()

            for moment in minutes(first, NOW + timedelta(minutes=1)):
                Clock.moment = moment
                local = moment.astimezone(ZONE)
                day = local.date()
                if local.hour == 0 and local.minute == 0 and moment < window:
                    for appliance, start in house_data.past_starts(day).items():
                        house.start(appliance, start)
                values = house.step(moment)
                ha.values = values
                minute = local.hour * 60 + local.minute
                for entity_id, value in values.items():
                    target = by_entity.get(entity_id)
                    if target and house_data.changed(entity_id, value, last.get(entity_id), minute):
                        buffer.append(Reading(entity_id, target.sensor_iri, float(value), moment))
                        last[entity_id] = value
                end_of_day = local.hour == 23 and local.minute == 59
                if moment < window and not end_of_day:
                    continue
                if moment >= window:
                    while pending_requests and pending_requests[0][0] <= moment:
                        _, appliance, latest = pending_requests.pop(0)
                        user_requests.ask(database, keys[appliance], latest, moment)
                if end_of_day or local.minute in (0, 15, 30, 45, 59):
                    flush()
                    await aggregator.step(moment + timedelta(minutes=1))
                if end_of_day:
                    for old in raw.days():
                        if old < day - timedelta(days=RAW_DAYS - 1):
                            raw.remove_day(old)
                if moment >= window and local.minute == 59:
                    context = runner.Context(
                        client=client,
                        model=model,
                        reader=aggregator,
                        raw=raw,
                        database=database,
                        settings=load_settings(database),
                        configuration=settings,
                    )
                    report = await runner.run(context, moment)
                    summary["runs"] += 1
                    if report.errors and not quiet:
                        print(f"{local:%d/%m %H:%M} : {report.errors}")
                    plan = PlanStore(database).load("today")
                    if plan is not None:
                        for appliance, start in planned_starts(plan.content, names).items():
                            soon = moment < start < moment + timedelta(minutes=60)
                            if soon and not house.started(appliance, start.date()):
                                house.start(appliance, start)
                                summary["starts"].append((appliance, start.isoformat()))
                    if not quiet:
                        planned = (
                            {
                                k: f"{v:%H:%M}"
                                for k, v in planned_starts(plan.content, names).items()
                            }
                            if plan is not None
                            else {}
                        )
                        print(f"{local:%d/%m %H:%M} ({report.seconds_today:.1f} s) {planned}")

            Clock.moment = NOW
            flush()
            await aggregator.step(NOW)
            runner.refresh_actual(model, raw, database, NOW, settings, manual=False)
            finish(database, followed, ha.values, NOW)
            summary["values"] = ha.values
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    raw.flush()
    graph.flush()
    database.close()
    (data_dir / "demo.json").write_text(
        json.dumps({"language": language, "now": NOW.isoformat(), "values": ha.values}, indent=1),
        encoding="utf-8",
    )
    return summary


def finish(
    database: Any, followed: dict[str, Any], values: dict[str, float], now: datetime
) -> None:
    """Historique de HA repris (étape « Historique » de la mise en route) et dernier relevé écrit
    par entité (reprise après coupure de l'ingestion), comme après 31 jours de service."""
    since = (now - timedelta(days=house_data.HISTORY_DAYS)).astimezone(UTC)
    with database:
        database.executemany(
            "INSERT OR REPLACE INTO history_import VALUES (?, ?, ?, ?, ?, ?)",
            [
                (entity_id, since.isoformat(), 960, since.isoformat(), 744, since.isoformat())
                for entity_id in followed
            ],
        )
        database.executemany(
            "INSERT INTO ingestion_state (entity_id, last_time, last_value) VALUES (?, ?, ?) "
            "ON CONFLICT(entity_id) DO UPDATE SET last_time = excluded.last_time, "
            "last_value = excluded.last_value",
            [
                (entity_id, now.astimezone(UTC).isoformat(), float(values[entity_id]))
                for entity_id in followed
                if entity_id in values
            ],
        )


# --- Service --------------------------------------------------------------------------------


async def serve(data_dir: Path, port: int, ha_port: int) -> None:
    """Application sur le dossier de démonstration, heure figée, connectée au faux HA."""
    import uvicorn

    import_application()
    Clock.moment = NOW
    from wattslot.main import create_app
    from wattslot.runtime import HomeAssistantTarget, RunMode, Settings

    saved = json.loads((data_dir / "demo.json").read_text(encoding="utf-8"))
    ha = FakeHomeAssistant(saved["language"], saved["values"])
    async with ha.running(ha_port) as bound:
        settings = Settings(
            mode=RunMode.STANDALONE,
            data_dir=data_dir,
            static_dir=FRONTEND if FRONTEND.is_dir() else None,
            home_assistant=HomeAssistantTarget(f"ws://localhost:{bound}/api/websocket", TOKEN),
            connection_source="env",
        )
        app = create_app(settings)
        freeze_time()  # après la déclaration des routes, dont les annotations lisent ``datetime``
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        await server.serve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="dossier de données de la démonstration")
    gen.add_argument("--language", choices=sorted(NAMES), default="en")
    gen.add_argument("--data", type=Path, required=True)
    run = sub.add_parser("serve", help="application sur le dossier, heure figée")
    run.add_argument("--data", type=Path, required=True)
    run.add_argument("--port", type=int, default=8100)
    run.add_argument("--ha-port", type=int, default=0, help="port du faux HA (0 : libre)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.command == "generate":
        summary = asyncio.run(generate(args.data, args.language))
        print(f"{summary['runs']} calculs, {summary['readings']} relevés, {summary['starts']}")
    else:
        asyncio.run(serve(args.data, args.port, args.ha_port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
