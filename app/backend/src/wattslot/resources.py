"""Ressources de l'application : processeur, mémoire et disque (État de l'application).

Un relevé par minute, gardé en mémoire sur 24 heures : le temps processeur du processus et sa
mémoire résidente. Le processeur se lit en moyenne sur 15 minutes (en pourcentage d'un cœur),
jamais en valeur instantanée : WattSlot dort la plupart du temps et travaille par à-coups, au
calcul horaire du plan. Les limites sont celles du conteneur (cgroup v2, ou v1) quand il y en a,
sinon celles de la machine ; le disque est celui qui porte le dossier des données (en module
complémentaire, celui de Home Assistant).

Les alertes (disque, mémoire) sont des problèmes du diagnostic : ``problems._resource_problems``.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from wattslot.maintenance import directory_size
from wattslot.storage.database import DATABASE_FILENAME
from wattslot.storage.graph import GRAPH_DIRNAME

logger = logging.getLogger(__name__)

INTERVAL_S = 60
AVERAGE_S = 15 * 60  # fenêtre de la moyenne du processeur
HISTORY_S = 24 * 3600  # relevés gardés (pics)
# cgroup v1 : « pas de limite » s'écrit comme un très grand nombre.
UNLIMITED_V1 = 1 << 60

# Seuils des alertes (provisoires, à revoir d'après des mesures réelles) : ici pour que les
# problèmes du diagnostic et la ligne rouge des courbes partent des mêmes valeurs.
DISK_FREE_MIN = 2 * 10**9  # octets libres sur le disque des données
DISK_FREE_MIN_SHARE = 0.10  # part libre de ce disque
BACKUP_MARGIN = 2  # une sauvegarde copie la base et le graphe : deux fois leur taille
MEMORY_CONTAINER_SHARE = 0.75  # de la limite du conteneur, tenue 15 minutes
MEMORY_MAX = 1 << 30  # sans limite de conteneur : mémoire de WattSlot seul, tenue 15 minutes

CGROUP = Path("/sys/fs/cgroup")
MEMINFO = Path("/proc/meminfo")


@dataclass(frozen=True)
class Sample:
    at: float  # horloge monotone, en secondes
    cpu_s: float  # temps processeur du processus depuis son démarrage (utilisateur + système)
    memory: int | None  # mémoire résidente
    disk_free: int | None = None  # espace libre du disque des données
    time: datetime | None = None  # heure du relevé (courbes)


class Resources(BaseModel):
    cpu_percent: float | None = None  # moyenne sur 15 min, en % d'un cœur
    cpu_peak_percent: float | None = None  # minute la plus chargée des dernières 24 h
    cpu_cores: float | None = None  # cœurs à la disposition de l'application
    memory_bytes: int | None = None  # mémoire résidente (Linux)
    memory_peak_bytes: int | None = None  # plus haut relevé des dernières 24 h
    # Plus bas relevé des 15 dernières minutes : une alerte sur une consommation qui dure.
    memory_floor_bytes: int | None = None
    memory_limit_bytes: int | None = None  # limite du conteneur, sinon mémoire de la machine
    memory_limit_source: Literal["container", "machine"] | None = None
    disk_used_bytes: int | None = None  # dossier des données de l'application
    disk_free_bytes: int | None = None  # espace libre du disque qui le porte
    disk_total_bytes: int | None = None
    disk_backup_bytes: int | None = None  # place qu'une sauvegarde demande (base et graphe)
    # Seuils des alertes, pour la ligne rouge des courbes : mémoire au-delà, espace libre en deçà.
    memory_alert_bytes: int | None = None
    disk_alert_free_bytes: int | None = None
    measured_s: int = 0  # durée couverte par les relevés (moins de 24 h après un démarrage)


def memory_alert(resources: Resources) -> int | None:
    """Mémoire au-delà de laquelle WattSlot alerte : une part de la limite du conteneur, ou,
    sans limite de conteneur (mémoire de la machine, partagée), un plafond pour lui seul."""
    limit = resources.memory_limit_bytes
    if resources.memory_limit_source == "container" and limit:
        return round(MEMORY_CONTAINER_SHARE * limit)
    return MEMORY_MAX


def disk_low_free(resources: Resources) -> int:
    """Espace libre en deçà duquel le disque est « presque plein »."""
    return max(DISK_FREE_MIN, round(DISK_FREE_MIN_SHARE * (resources.disk_total_bytes or 0)))


def disk_alert(resources: Resources) -> int | None:
    """Espace libre en deçà duquel une alerte part : disque presque plein, ou sauvegarde qui ne
    tiendrait plus."""
    if resources.disk_free_bytes is None:
        return None
    return max(disk_low_free(resources), resources.disk_backup_bytes or 0)


def cpu_percent(older: Sample, newer: Sample) -> float | None:
    """Charge entre deux relevés, en pourcentage d'un cœur."""
    elapsed = newer.at - older.at
    if elapsed <= 0:
        return None
    return max(0.0, (newer.cpu_s - older.cpu_s) / elapsed * 100)


def summarize(samples: list[Sample], now: Sample) -> Resources:
    """Moyenne, pics et durée couverte, d'après les relevés (les plus anciens d'abord) et
    l'instant présent."""
    if not samples:
        return Resources(
            memory_bytes=now.memory, memory_peak_bytes=now.memory, memory_floor_bytes=now.memory
        )
    window = [s for s in samples if now.at - s.at <= AVERAGE_S] or samples[-1:]
    series = [*samples, now]
    # Pics par minute : l'intervalle en cours n'y entre qu'une fois assez long (quelques
    # secondes seulement donneraient un pic de hasard).
    pairs = list(pairwise(series if now.at - samples[-1].at >= INTERVAL_S / 2 else samples))
    peaks = [cpu_percent(a, b) for a, b in pairs]
    memories = [s.memory for s in series if s.memory is not None]
    recent = [s.memory for s in [*window, now] if s.memory is not None]
    return Resources(
        cpu_percent=cpu_percent(window[0], now),
        cpu_peak_percent=max((p for p in peaks if p is not None), default=None),
        memory_bytes=now.memory,
        memory_peak_bytes=max(memories, default=None),
        memory_floor_bytes=min(recent, default=None),
        measured_s=round(now.at - samples[0].at),
    )


def memory_limit_v2(text: str) -> int | None:
    """``memory.max`` de cgroup v2 : un nombre d'octets, ou ``max`` sans limite."""
    value = text.strip()
    return None if value == "max" or not value.isdigit() else int(value)


def memory_limit_v1(text: str) -> int | None:
    value = text.strip()
    if not value.isdigit() or int(value) >= UNLIMITED_V1:
        return None
    return int(value)


def memory_total(meminfo: str) -> int | None:
    """``MemTotal`` dans le contenu de ``/proc/meminfo``."""
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return None


def cpu_limit_v2(text: str) -> float | None:
    """``cpu.max`` de cgroup v2 : « quota période » en microsecondes, ou ``max période``."""
    parts = text.split()
    if len(parts) != 2 or parts[0] == "max":
        return None
    try:
        return int(parts[0]) / int(parts[1])
    except (ValueError, ZeroDivisionError):
        return None


def cpu_limit_v1(quota: str, period: str) -> float | None:
    try:
        quota_us, period_us = int(quota), int(period)
    except ValueError:
        return None
    return quota_us / period_us if quota_us > 0 and period_us > 0 else None


def resident_bytes(proc_status: str) -> int | None:
    """Mémoire résidente (``VmRSS``) dans le contenu de ``/proc/self/status``."""
    for line in proc_status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return None


def memory_bytes() -> int | None:
    """Mémoire résidente du processus ; inconnue hors de Linux."""
    if not os.path.exists("/proc/self/status"):
        return None
    try:
        return resident_bytes(Path("/proc/self/status").read_text())
    except OSError:
        return None


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


MemorySource = Literal["container", "machine"]


def memory_limit(
    root: Path = CGROUP, meminfo: Path = MEMINFO
) -> tuple[int, MemorySource] | tuple[None, None]:
    """La plus petite des limites connues, et d'où elle vient : conteneur (cgroup v2 puis v1)
    ou machine. Dans un conteneur sans limite (le cas courant d'un module complémentaire),
    c'est la mémoire de la machine, partagée avec le reste ; dans un LXC, celle du LXC."""
    container: int | None = None
    if (text := _read(root / "memory.max")) is not None:
        container = memory_limit_v2(text)
    elif (text := _read(root / "memory" / "memory.limit_in_bytes")) is not None:
        container = memory_limit_v1(text)
    text = _read(meminfo)
    machine = memory_total(text) if text is not None else None
    if container is not None and (machine is None or container < machine):
        return container, "container"
    if machine is not None:
        return machine, "machine"
    return None, None


def cpu_cores(root: Path = CGROUP) -> float | None:
    """Cœurs utilisables : ceux du processus, bornés par le quota du conteneur."""
    affinity = getattr(os, "sched_getaffinity", None)
    cores: float | None = len(affinity(0)) if affinity else os.cpu_count()
    quota: float | None = None
    if (text := _read(root / "cpu.max")) is not None:
        quota = cpu_limit_v2(text)
    else:
        v1_quota = _read(root / "cpu" / "cpu.cfs_quota_us")
        v1_period = _read(root / "cpu" / "cpu.cfs_period_us")
        if v1_quota is not None and v1_period is not None:
            quota = cpu_limit_v1(v1_quota, v1_period)
    if quota is None:
        return cores
    return quota if cores is None else min(cores, quota)


class ResourcePoint(BaseModel):
    """Un point des courbes : la minute écoulée jusqu'à ``time``."""

    time: datetime
    cpu_percent: float | None = None  # charge de la minute, en % d'un cœur
    memory_bytes: int | None = None
    disk_free_bytes: int | None = None


def history(samples: list[Sample]) -> list[ResourcePoint]:
    """Courbes des dernières 24 h d'après les relevés (les plus anciens d'abord) ; le premier
    relevé n'a pas de charge, faute de minute avant lui."""
    points = []
    previous: Sample | None = None
    for sample in samples:
        if sample.time is not None:
            points.append(
                ResourcePoint(
                    time=sample.time,
                    cpu_percent=cpu_percent(previous, sample) if previous else None,
                    memory_bytes=sample.memory,
                    disk_free_bytes=sample.disk_free,
                )
            )
        previous = sample
    return points


def _free(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _sample(data_dir: Path | None = None) -> Sample:
    return Sample(
        at=time.monotonic(),
        cpu_s=time.process_time(),
        memory=memory_bytes(),
        disk_free=_free(data_dir) if data_dir is not None else None,
        time=datetime.now(UTC),
    )


class ResourceMonitor:
    """Relève le processeur, la mémoire et l'espace libre toutes les minutes ; ``snapshot`` y
    ajoute le dossier des données et les limites (à appeler hors de la boucle d'événements : il
    parcourt ce dossier)."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._samples: deque[Sample] = deque(maxlen=HISTORY_S // INTERVAL_S + 1)
        self._samples.append(_sample(data_dir))  # point de départ de la première moyenne
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def record(self, sample: Sample) -> None:
        self._samples.append(sample)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(INTERVAL_S)
            try:
                self.record(_sample(self._data_dir))
            except Exception:  # nouvel essai à la minute suivante
                logger.exception("Relevé des ressources impossible")

    def history(self) -> list[ResourcePoint]:
        return history(list(self._samples))

    def snapshot(self, now: Sample | None = None) -> Resources:
        found = summarize(list(self._samples), now or _sample())
        found.cpu_cores = cpu_cores()
        found.memory_limit_bytes, found.memory_limit_source = memory_limit()
        found.disk_used_bytes = directory_size(self._data_dir)
        found.disk_backup_bytes = BACKUP_MARGIN * (
            directory_size(self._data_dir / GRAPH_DIRNAME)
            + sum(
                directory_size(self._data_dir / f"{DATABASE_FILENAME}{suffix}")
                for suffix in ("", "-wal", "-shm")
            )
        )
        try:
            usage = shutil.disk_usage(self._data_dir)
        except OSError:
            usage = None
        if usage is not None:
            found.disk_free_bytes, found.disk_total_bytes = usage.free, usage.total
        found.memory_alert_bytes = memory_alert(found)
        found.disk_alert_free_bytes = disk_alert(found)
        return found
