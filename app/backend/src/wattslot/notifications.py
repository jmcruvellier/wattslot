"""Notifications personnalisables (lot 5.6, point n° 6).

Un catalogue de notifications activables, chacune avec son appareil ``notify.*`` (celui commun
par défaut) et ses heures de silence, envoyées par HA après chaque calcul planifié. Rien n'est
activé par défaut, pour ne pas doubler la v1 tant qu'elle notifie.

La recommandation du jour (PR 1), avec son rythme : à chaque calcul (comme la v1), seulement
quand le plan change, ou une fois par jour à une heure donnée. Pendant les heures de silence,
une notification est sautée, pas différée ; celle « quand le plan change » ou « une fois par
jour » part au premier calcul après le silence, puisqu'elle n'a pas encore été envoyée.

Les quatre autres (PR 2, conditions et textes dans ``notification_events``) partent une seule
fois par clé (équipement, cause…) et par jour : « lancez X maintenant », écart au plan, batterie
pleine avant midi, prévision de demain qui chute.

Les réglages sont gardés dans ``app_settings`` ; sans réglage enregistré, ceux d'avant le lot
5.6 (``notify_service`` et ``notify_language`` des réglages du calcul) s'appliquent.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, time
from typing import Any, Literal, get_args
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from wattslot import notification_events as events
from wattslot.home_assistant import HomeAssistantClient
from wattslot.languages import Language
from wattslot.planning.recommendation import recommendation, title
from wattslot.planning.sources import load_settings
from wattslot.planning.store import PlanStore

SETTINGS_KEY = "notifications"
SERVICE_PATTERN = r"^notify\.[a-z0-9_]+$"

Kind = Literal["recommendation", "device_now", "plan_gap", "battery_full", "forecast_drop"]
EVENT_KINDS: tuple[Kind, ...] = ("device_now", "plan_gap", "battery_full", "forecast_drop")
FORECAST_KEY = "notifications_forecast_reference"  # plus haute prévision vue pour demain
Cadence = Literal["every_run", "when_changed", "daily"]


class QuietHours(BaseModel):
    """Heures de silence [début, fin[ ; elles passent minuit si la fin précède le début."""

    start: time = time(22, 0)
    end: time = time(7, 0)

    def contains(self, moment: time) -> bool:
        if self.start <= self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


class Rule(BaseModel):
    enabled: bool = False
    service: str | None = Field(default=None, pattern=SERVICE_PATTERN)  # aucun : le commun
    quiet_hours: QuietHours | None = None


class RecommendationRule(Rule):
    cadence: Cadence = "every_run"  # comme la v1 (n8n, chaque heure)
    daily_at: time = time(7, 0)  # rythme « une fois par jour »


class NotificationSettings(BaseModel):
    service: str | None = Field(default=None, pattern=SERVICE_PATTERN)  # appareil commun
    language: Language = "fr"  # une des six langues (lot 5.7)
    recommendation: RecommendationRule = RecommendationRule()
    device_now: Rule = Rule()
    plan_gap: Rule = Rule()
    battery_full: Rule = Rule()
    forecast_drop: Rule = Rule()

    def service_of(self, kind: Kind) -> str | None:
        rule: Rule = getattr(self, kind)
        return rule.service or self.service

    def active(self) -> bool:
        """Au moins une notification activée qui a un appareil (le sien ou le commun)."""
        return any(
            getattr(self, kind).enabled and self.service_of(kind) is not None
            for kind in get_args(Kind)
        )


def load(database: sqlite3.Connection) -> NotificationSettings:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (SETTINGS_KEY,)
    ).fetchone()
    if row:
        return NotificationSettings.model_validate(json.loads(row[0]))
    # Réglages d'avant le lot 5.6 : la recommandation part si un service est choisi.
    planning = load_settings(database)
    return NotificationSettings(
        service=planning.notify_service,
        language=planning.notify_language,
        recommendation=RecommendationRule(enabled=planning.notify_service is not None),
    )


def save(database: sqlite3.Connection, settings: NotificationSettings) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, settings.model_dump_json()),
        )


def _fingerprint(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def last_sent(database: sqlite3.Connection, kind: str, key: str) -> tuple[str, str] | None:
    """Jour et empreinte du dernier envoi de cette notification."""
    row = database.execute(
        "SELECT day, fingerprint FROM notifications_sent WHERE kind = ? AND key = ? "
        "ORDER BY sent_at DESC LIMIT 1",
        (kind, key),
    ).fetchone()
    return (row[0], row[1]) if row else None


def record(
    database: sqlite3.Connection, kind: str, key: str, now: datetime, day: str, message: str
) -> None:
    with database:
        database.execute(
            "INSERT INTO notifications_sent (kind, key, day, sent_at, fingerprint) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(kind, key, day) DO UPDATE SET "
            "sent_at = excluded.sent_at, fingerprint = excluded.fingerprint",
            (kind, key, day, now.isoformat(), _fingerprint(message)),
        )


def due(
    rule: RecommendationRule, previous: tuple[str, str] | None, local: datetime, message: str
) -> bool:
    """La recommandation part-elle à ce calcul, selon son rythme ?"""
    if rule.cadence == "every_run":
        return True
    if rule.cadence == "when_changed":
        return previous is None or previous[1] != _fingerprint(message)
    return local.time() >= rule.daily_at and (
        previous is None or previous[0] != local.date().isoformat()
    )


class Sent(BaseModel):
    kind: Kind
    service: str
    message: str


def notification_title(kind: Kind, lang: str) -> str:
    return title(lang) if kind == "recommendation" else events.text(lang, f"{kind}.title")


async def send(
    client: HomeAssistantClient, service: str, kind: Kind, message: str, lang: str
) -> None:
    """Notification par un service ``notify.*`` de HA."""
    domain, name = service.split(".", 1)
    await client.command(
        "call_service",
        domain=domain,
        service=name,
        service_data={"title": notification_title(kind, lang), "message": message},
    )


def already_sent(database: sqlite3.Connection, kind: str, key: str, day: str) -> bool:
    row = database.execute(
        "SELECT 1 FROM notifications_sent WHERE kind = ? AND key = ? AND day = ?",
        (kind, key, day),
    ).fetchone()
    return row is not None


def forecast_reference(database: sqlite3.Connection, state: dict[str, Any] | None) -> float | None:
    """Plus haute prévision vue jusque-là pour demain (avant celle-ci), puis mise à jour."""
    if state is None:
        return None
    day = str(state.get("date_cible"))
    kwh = events.tomorrow_production(state)
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (FORECAST_KEY,)
    ).fetchone()
    stored = json.loads(row[0]) if row else {}
    reference = stored.get("kwh") if stored.get("day") == day else None
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (FORECAST_KEY, json.dumps({"day": day, "kwh": max(kwh, reference or 0.0)})),
        )
    return float(reference) if reference is not None else None


def candidates(
    kind: Kind,
    today: dict[str, Any] | None,
    tomorrow: dict[str, Any] | None,
    reference: float | None,
    local: datetime,
    lang: str,
) -> list[events.Candidate]:
    if kind == "forecast_drop":
        return events.forecast_drop(tomorrow, reference, lang) if tomorrow else []
    if today is None:
        return []
    if kind == "device_now":
        return events.device_now(today, local, lang)
    if kind == "plan_gap":
        return events.plan_gap(today, local, lang)
    return events.battery_full(today, local, lang)


def _quiet(rule: Rule, local: datetime) -> bool:
    return rule.quiet_hours is not None and rule.quiet_hours.contains(local.time())


async def dispatch(
    client: HomeAssistantClient,
    database: sqlite3.Connection,
    now: datetime,
    zone: ZoneInfo,
    errors: list[str] | None = None,
) -> list[Sent]:
    """Notifications à envoyer après un calcul planifié ; renvoie celles envoyées. Avec
    ``errors`` (bilan du calcul), l'échec d'une notification y est noté sans empêcher les autres ;
    sans, il remonte."""
    settings = load(database)
    local = now.astimezone(zone)
    lang = settings.language
    store = PlanStore(database)
    today_plan, tomorrow_plan = store.load("today"), store.load("tomorrow")
    today = today_plan.content if today_plan else None
    tomorrow = tomorrow_plan.content if tomorrow_plan else None
    # Toujours tenue à jour, même désactivée : la baisse se mesure dès qu'on l'active.
    reference = forecast_reference(database, tomorrow)
    sent: list[Sent] = []

    def failed(kind: Kind, exc: Exception) -> None:
        if errors is None:
            raise exc
        errors.append(f"notification {kind} : {type(exc).__name__}: {exc}")

    async def deliver(kind: Kind, key: str, day: str, message: str, service: str) -> None:
        await send(client, service, kind, message, lang)
        record(database, kind, key, now, day, message)
        sent.append(Sent(kind=kind, service=service, message=message))

    rule = settings.recommendation
    service = settings.service_of("recommendation")
    if rule.enabled and service is not None and today is not None and not _quiet(rule, local):
        message = recommendation(today, lang)
        if due(rule, last_sent(database, "recommendation", "plan"), local, message):
            try:
                await deliver("recommendation", "plan", local.date().isoformat(), message, service)
            except Exception as exc:  # noqa: BLE001 — noté, les autres continuent
                failed("recommendation", exc)

    for kind in EVENT_KINDS:
        event_rule: Rule = getattr(settings, kind)
        service = settings.service_of(kind)
        if not event_rule.enabled or service is None or _quiet(event_rule, local):
            continue
        try:
            for found in candidates(kind, today, tomorrow, reference, local, lang):
                if not already_sent(database, kind, found.key, found.day):
                    await deliver(kind, found.key, found.day, found.message, service)
        except Exception as exc:  # noqa: BLE001 — noté, les autres continuent
            failed(kind, exc)
    return sent


# Exemples des envois d'essai quand la condition n'est pas réunie au moment de l'essai ; une
# heure vide prend celle de l'essai.
SAMPLES: dict[Kind, tuple[str, dict[str, str]]] = {
    "device_now": ("device_now", {"device": "Lave-linge", "time": "", "kwh": "1.0"}),
    "plan_gap": ("plan_gap.cycle", {"device": "Lave-linge", "time": ""}),
    "battery_full": ("battery_full", {"time": ""}),
    "forecast_drop": ("forecast_drop", {"kwh": "6.0", "reference": "12.0", "gap": "-50"}),
}


def sample(kind: Kind, local: datetime, lang: str) -> str:
    key, params = SAMPLES[kind]
    moment = events.clock(local.hour * 60 + local.minute, lang)
    return events.text(lang, key, **{name: value or moment for name, value in params.items()})


async def send_test(
    client: HomeAssistantClient,
    database: sqlite3.Connection,
    kind: Kind,
    now: datetime | None = None,
    zone: ZoneInfo | None = None,
) -> Sent:
    """Envoi d'essai, tout de suite, sans heures de silence ni rythme, et sans le noter. La
    recommandation est celle du plan du jour ; les autres, marquées « [Essai] », une candidate
    du moment s'il y en a, sinon un exemple. ``LookupError`` : « no_notify_service » ou
    « no_plan »."""
    settings = load(database)
    lang = settings.language
    service = settings.service_of(kind)
    if service is None:
        raise LookupError("no_notify_service")
    plan = PlanStore(database).load("today")
    if kind == "recommendation":
        if plan is None:
            raise LookupError("no_plan")
        message = recommendation(plan.content, lang)
    else:
        local = (now or datetime.now(zone)).astimezone(zone)
        # Sans référence pour la prévision de demain : toujours l'exemple.
        found = (
            candidates(kind, plan.content, None, None, local, lang)
            if plan is not None and kind != "forecast_drop"
            else []
        )
        current = found[0].message if found else sample(kind, local, lang)
        message = events.text(lang, "test", message=current)
    await send(client, service, kind, message, lang)
    return Sent(kind=kind, service=service, message=message)
