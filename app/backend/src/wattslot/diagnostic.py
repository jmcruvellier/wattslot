"""Diagnostic (lot 1.5) : tout ce qu'il faut pour voir d'un coup d'œil que l'application tourne.

Rassemble en une réponse l'état de l'ingestion (avec les relevés écrits aujourd'hui par entité),
de l'agrégation, de la maintenance (volumes sur disque), du planificateur des calculs (lot 2.3),
la mémoire du processus, les octets qu'il a écrits sur disque (usure du SSD) et les anomalies de
configuration détectées dans le tableau Énergie (lot 1.1).
"""

from datetime import UTC, datetime

from pydantic import BaseModel

from wattslot.aggregation import AggregationStatus, Aggregator
from wattslot.detection import Issue, propose
from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.ingestion import IngestionStatus, Ingestor, silent_entities
from wattslot.maintenance import Maintenance, MaintenanceStatus
from wattslot.planning.scheduler import PlanningScheduler, SchedulerStatus
from wattslot.resources import (
    ResourceMonitor,
    Resources,
    disk_written_bytes,
    memory_bytes,
)
from wattslot.storage.raw import RawStores

STARTED_AT = datetime.now(UTC)  # chargement du module, au démarrage de l'application


class DeviceIssue(BaseModel):
    device: str  # nom de l'équipement proposé
    key: str | None = None  # clé de l'équipement proposé (celle de la maison enregistrée)
    entity_id: str | None = None  # capteur concerné, s'il y en a un
    issue: Issue


class Diagnostic(BaseModel):
    generated_at: datetime
    memory_bytes: int | None = None  # mémoire résidente du processus (Linux)
    started_at: datetime | None = None  # démarrage du processus
    written_bytes: int | None = None  # octets écrits sur disque depuis (Linux)
    ingestion: IngestionStatus | None = None
    today: dict[str, int] = {}  # relevés écrits aujourd'hui (heure locale), par entité
    silent: list[str] = []  # entités muettes à valeur figée suspecte (``silent_entities``)
    aggregation: AggregationStatus | None = None
    maintenance: MaintenanceStatus | None = None
    planning: SchedulerStatus | None = None
    issues: list[DeviceIssue] | None = None  # None : HA non connecté, anomalies inconnues
    resources: Resources | None = None  # processeur, mémoire et disque


def configuration_issues(client: HomeAssistantClient | None) -> list[DeviceIssue] | None:
    if client is None or client.status.state is not ConnectionState.CONNECTED:
        return None
    found: list[DeviceIssue] = []
    for device in propose(client.snapshot).devices:
        found += [
            DeviceIssue(device=device.name, key=device.key, issue=issue) for issue in device.issues
        ]
        for sensor in device.sensors:
            found += [
                DeviceIssue(
                    device=device.name, key=device.key, entity_id=sensor.entity_id, issue=issue
                )
                for issue in sensor.issues
            ]
    return found


def readings_today(ingestor: Ingestor, raw: RawStores) -> dict[str, int]:
    by_sensor = raw.counts_by_sensor(raw.day_of(datetime.now(UTC)))
    return {
        entity_id: by_sensor.get(target.sensor_iri, 0)
        for entity_id, target in ingestor.targets.items()
    }


def diagnostic(
    client: HomeAssistantClient | None,
    ingestor: Ingestor | None,
    raw: RawStores | None,
    aggregator: Aggregator | None,
    maintenance: Maintenance | None,
    scheduler: PlanningScheduler | None = None,
    resources: ResourceMonitor | None = None,
) -> Diagnostic:
    """Lit les disques et le magasin du jour : à appeler hors de la boucle d'événements."""
    now = datetime.now(UTC)
    ingestion = ingestor.status() if ingestor else None
    today = readings_today(ingestor, raw) if ingestor and raw else {}
    return Diagnostic(
        generated_at=now,
        memory_bytes=memory_bytes(),
        started_at=STARTED_AT,
        written_bytes=disk_written_bytes(),
        ingestion=ingestion,
        today=today,
        silent=silent_entities(ingestion, today, now),
        aggregation=aggregator.status() if aggregator else None,
        maintenance=maintenance.status() if maintenance else None,
        planning=scheduler.status() if scheduler else None,
        issues=configuration_issues(client),
        resources=resources.snapshot() if resources else None,
    )
