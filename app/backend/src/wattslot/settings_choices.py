"""Choix proposés par le formulaire des réglages de fonctionnement (lot 4.2) : listes de tâches,
services de notification et entités de prévision de repli, lus dans HA au moment de la demande.

Un service de notification n'est pas une entité (l'app compagnon déclare ``notify.mobile_app_…``
sans entité) : il est lu par la commande ``get_services``. Sans HA connecté, les listes sont vides
et le formulaire garde la saisie libre.
"""

from typing import Any

from pydantic import BaseModel

from wattslot.home_assistant import ConnectionState, HomeAssistantClient, HomeSnapshot

# « notify.send_message » vise une entité ``notify.*`` : il ne s'utilise pas comme service seul.
_NOT_SERVICES = {"send_message"}


class Choice(BaseModel):
    id: str  # entity_id, ou « notify.<service> »
    name: str | None = None


class SettingsChoices(BaseModel):
    connected: bool
    todo_lists: list[Choice] = []
    notify_services: list[Choice] = []
    forecast_entities: list[Choice] = []


def _name(state: dict[str, Any]) -> str | None:
    name = (state.get("attributes") or {}).get("friendly_name")
    return str(name) if name else None


def todo_lists(snapshot: HomeSnapshot) -> list[Choice]:
    return [
        Choice(id=entity_id, name=_name(state))
        for entity_id, state in sorted(snapshot.states.items())
        if entity_id.startswith("todo.")
    ]


def forecast_entities(snapshot: HomeSnapshot) -> list[Choice]:
    """Entités au format de Helios : attribut ``forecast``, points ``datetime`` / ``watts``."""
    found = []
    for entity_id, state in sorted(snapshot.states.items()):
        points = (state.get("attributes") or {}).get("forecast")
        if isinstance(points, list) and any(
            isinstance(p, dict) and "datetime" in p and "watts" in p for p in points
        ):
            found.append(Choice(id=entity_id, name=_name(state)))
    return found


def notify_services(services: Any) -> list[Choice]:
    """Services ``notify.*`` de la réponse à ``get_services`` (``{domaine: {service: …}}``)."""
    notify = (services or {}).get("notify") or {}
    return [
        Choice(id=f"notify.{service}", name=(notify[service] or {}).get("name") or None)
        for service in sorted(notify)
        if service not in _NOT_SERVICES
    ]


async def settings_choices(client: HomeAssistantClient | None) -> SettingsChoices:
    if client is None or client.status.state is not ConnectionState.CONNECTED:
        return SettingsChoices(connected=False)
    try:
        services = await client.command("get_services")
    except Exception:  # noqa: BLE001 — sans la liste, la saisie libre reste possible
        services = {}
    snapshot = client.snapshot
    return SettingsChoices(
        connected=True,
        todo_lists=todo_lists(snapshot),
        notify_services=notify_services(services),
        forecast_entities=forecast_entities(snapshot),
    )
