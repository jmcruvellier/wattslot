"""Ressources de l'application : processeur, mémoire et disque (État de l'application).

Un relevé par minute, gardé en mémoire sur 24 heures : le temps processeur du processus et sa
mémoire résidente. Le processeur se lit en moyenne sur 15 minutes (en pourcentage d'un cœur),
jamais en valeur instantanée : WattSlot dort la plupart du temps et travaille par à-coups, au
calcul horaire du plan. Les limites sont celles du conteneur (cgroup v2, ou v1) quand il y en a,
sinon celles de la machine ; le disque est celui qui porte le dossier des données (en module
complémentaire, celui de Home Assistant).

Première étape : mesurer et afficher, sans alerte ; les seuils viendront de mesures réelles.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import time
from collections import deque
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from pydantic import BaseModel

from wattslot.maintenance import directory_size

logger = logging.getLogger(__name__)

INTERVAL_S = 60
AVERAGE_S = 15 * 60  # fenêtre de la moyenne du processeur
HISTORY_S = 24 * 3600  # relevés gardés (pics)
# cgroup v1 : « pas de limite » s'écrit comme un très grand nombre.
UNLIMITED_V1 = 1 << 60

CGROUP = Path("/sys/fs/cgroup")
MEMINFO = Path("/proc/meminfo")


@dataclass(frozen=True)
class Sample:
    at: float  # horloge monotone, en secondes
    cpu_s: float  # temps processeur du processus depuis son démarrage (utilisateur + système)
    memory: int | None  # mémoire résidente


class Resources(BaseModel):
    cpu_percent: float | None = None  # moyenne sur 15 min, en % d'un cœur
    cpu_peak_percent: float | None = None  # minute la plus chargée des dernières 24 h
    cpu_cores: float | None = None  # cœurs à la disposition de l'application
    memory_bytes: int | None = None  # mémoire résidente (Linux)
    memory_peak_bytes: int | None = None  # plus haut relevé des dernières 24 h
    memory_limit_bytes: int | None = None  # limite du conteneur, sinon mémoire de la machine
    disk_used_bytes: int | None = None  # dossier des données de l'application
    disk_free_bytes: int | None = None  # espace libre du disque qui le porte
    disk_total_bytes: int | None = None
    measured_s: int = 0  # durée couverte par les relevés (moins de 24 h après un démarrage)


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
        return Resources(memory_bytes=now.memory, memory_peak_bytes=now.memory)
    window = [s for s in samples if now.at - s.at <= AVERAGE_S] or samples[-1:]
    series = [*samples, now]
    # Pics par minute : l'intervalle en cours n'y entre qu'une fois assez long (quelques
    # secondes seulement donneraient un pic de hasard).
    pairs = list(pairwise(series if now.at - samples[-1].at >= INTERVAL_S / 2 else samples))
    peaks = [cpu_percent(a, b) for a, b in pairs]
    memories = [s.memory for s in series if s.memory is not None]
    return Resources(
        cpu_percent=cpu_percent(window[0], now),
        cpu_peak_percent=max((p for p in peaks if p is not None), default=None),
        memory_bytes=now.memory,
        memory_peak_bytes=max(memories, default=None),
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


def memory_limit(root: Path = CGROUP, meminfo: Path = MEMINFO) -> int | None:
    """La plus petite des limites connues : conteneur (v2 puis v1) et machine."""
    limits: list[int | None] = []
    if (text := _read(root / "memory.max")) is not None:
        limits.append(memory_limit_v2(text))
    elif (text := _read(root / "memory" / "memory.limit_in_bytes")) is not None:
        limits.append(memory_limit_v1(text))
    if (text := _read(meminfo)) is not None:
        limits.append(memory_total(text))
    known = [limit for limit in limits if limit is not None]
    return min(known, default=None)


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


def _sample() -> Sample:
    return Sample(at=time.monotonic(), cpu_s=time.process_time(), memory=memory_bytes())


class ResourceMonitor:
    """Relève le processeur et la mémoire toutes les minutes ; ``snapshot`` y ajoute le disque
    et les limites (à appeler hors de la boucle d'événements : il parcourt le dossier des
    données)."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._samples: deque[Sample] = deque(maxlen=HISTORY_S // INTERVAL_S + 1)
        self._samples.append(_sample())  # point de départ de la première moyenne
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
                self.record(_sample())
            except Exception:  # nouvel essai à la minute suivante
                logger.exception("Relevé des ressources impossible")

    def snapshot(self, now: Sample | None = None) -> Resources:
        found = summarize(list(self._samples), now or _sample())
        found.cpu_cores = cpu_cores()
        found.memory_limit_bytes = memory_limit()
        found.disk_used_bytes = directory_size(self._data_dir)
        try:
            usage = shutil.disk_usage(self._data_dir)
        except OSError:
            return found
        found.disk_free_bytes, found.disk_total_bytes = usage.free, usage.total
        return found
