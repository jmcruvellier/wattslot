"""Diagnostic (lot 1.5) : tout ce qu'il faut pour voir d'un coup d'œil que l'application tourne.

Rassemble en une réponse l'état de l'ingestion (avec les relevés écrits aujourd'hui par entité),
de l'agrégation, de la maintenance (volumes sur disque), du planificateur des calculs (lot 2.3),
la mémoire du processus, les octets qu'il a écrits sur disque (usure du SSD) et les anomalies de
configuration détectées dans le tableau Énergie (lot 1.1).
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from wattslot.aggregation import AggregationStatus, Aggregator
from wattslot.detection import Issue, propose
from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.ingestion import IngestionStatus, Ingestor
from wattslot.maintenance import Maintenance, MaintenanceStatus
from wattslot.planning.scheduler import PlanningScheduler, SchedulerStatus
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
    aggregation: AggregationStatus | None = None
    maintenance: MaintenanceStatus | None = None
    planning: SchedulerStatus | None = None
    issues: list[DeviceIssue] | None = None  # None : HA non connecté, anomalies inconnues


def resident_bytes(proc_status: str) -> int | None:
    """Mémoire résidente (``VmRSS``) dans le contenu de ``/proc/self/status``."""
    for line in proc_status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return None


def written_from(proc_io: str) -> int | None:
    """Octets écrits sur disque (``write_bytes``) dans le contenu de ``/proc/self/io``."""
    for line in proc_io.splitlines():
        if line.startswith("write_bytes:"):
            return int(line.split()[1])
    return None


def disk_written_bytes() -> int | None:
    """Octets écrits sur disque par le processus depuis son démarrage ; inconnus hors de Linux."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        return written_from(Path("/proc/self/io").read_text())
    except OSError:
        return None


def memory_bytes() -> int | None:
    """Mémoire résidente du processus ; inconnue hors de Linux."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        return resident_bytes(Path("/proc/self/status").read_text())
    except OSError:
        return None


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
) -> Diagnostic:
    """Lit les disques et le magasin du jour : à appeler hors de la boucle d'événements."""
    return Diagnostic(
        generated_at=datetime.now(UTC),
        memory_bytes=memory_bytes(),
        started_at=STARTED_AT,
        written_bytes=disk_written_bytes(),
        ingestion=ingestor.status() if ingestor else None,
        today=readings_today(ingestor, raw) if ingestor and raw else {},
        aggregation=aggregator.status() if aggregator else None,
        maintenance=maintenance.status() if maintenance else None,
        planning=scheduler.status() if scheduler else None,
        issues=configuration_issues(client),
    )
