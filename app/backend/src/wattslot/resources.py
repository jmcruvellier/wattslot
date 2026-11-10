"""Ressources de l'application : processeur, mémoire et disque (État de l'application).

Un relevé par minute : le temps processeur du processus, sa mémoire résidente, l'espace libre
et les octets qu'il a écrits sur disque (Linux, ``/proc/self/io`` : base, graphe et ses
compactages, journaux), pour suivre l'usure d'une carte SD ou d'un SSD.
Chaque minute écoulée est aussi gardée en base (``resource_minutes``, 24 heures) avec un résumé
par heure (``resource_hours``, 30 jours) : les courbes et les pics survivent à un redémarrage, et
les seuils des alertes se règlent sur plusieurs jours de mesures.

Le processeur se lit en moyenne sur 15 minutes (en pourcentage d'un cœur), jamais en valeur
instantanée : WattSlot dort la plupart du temps et travaille par à-coups, au
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
import sqlite3
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
HISTORY_S = 24 * 3600  # relevés gardés (pics, courbes)
HOURS_KEPT = timedelta(days=30)  # résumés horaires gardés en base
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"  # largeur fixe : l'ordre du texte est celui du temps
# Taille du dossier des données (courbe) : un parcours de tout le dossier, pour une valeur qui
# bouge lentement, donc pas à chaque relevé.
DATA_SIZE_INTERVAL_S = 10 * 60
# cgroup v1 : « pas de limite » s'écrit comme un très grand nombre.
UNLIMITED_V1 = 1 << 60

# Seuils des alertes (provisoires, à revoir d'après des mesures réelles) : ici pour que les
# problèmes du diagnostic et la ligne rouge des courbes partent des mêmes valeurs.
DISK_FREE_MIN = 2 * 10**9  # octets libres sur le disque des données
DISK_FREE_MIN_SHARE = 0.20  # part libre de ce disque (80 % occupés)
DISK_FREE_MAX = 20 * 10**9  # un très grand disque n'alerte pas avec des centaines de Go libres
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
    disk_used: int | None = None  # dossier des données, mesuré toutes les 10 minutes seulement
    written: int | None = None  # octets écrits sur disque par le processus depuis son démarrage


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


def written_between(older: Sample, newer: Sample) -> int | None:
    """Octets écrits entre deux relevés ; inconnus si l'un manque ou si le compteur recule."""
    if older.written is None or newer.written is None or newer.written < older.written:
        return None
    return newer.written - older.written


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
    disk_alert_free_bytes: int | None = None  # le plus haut des deux seuils du disque
    # Le même seuil, pour les courbes où l'alerte part au-dessus de la ligne : en espace occupé du
    # disque, et en taille des données (la première des deux alertes qu'elles déclencheraient, si
    # rien d'autre ne remplissait le disque).
    disk_alert_used_bytes: int | None = None
    disk_alert_data_bytes: int | None = None
    measured_s: int = 0  # durée couverte par les relevés (moins de 24 h après un démarrage)
    # Octets écrits sur disque pendant les dernières 24 h (minutes relevées) ; aucun hors de Linux.
    written_day_bytes: int | None = None


def memory_alert(resources: Resources) -> int | None:
    """Mémoire au-delà de laquelle WattSlot alerte : une part de la limite du conteneur, ou,
    sans limite de conteneur (mémoire de la machine, partagée), un plafond pour lui seul."""
    limit = resources.memory_limit_bytes
    if resources.memory_limit_source == "container" and limit:
        return round(MEMORY_CONTAINER_SHARE * limit)
    return MEMORY_MAX


def disk_low_free(resources: Resources) -> int:
    """Espace libre en deçà duquel le disque est « presque plein » : 20 % du disque, entre 2 et
    20 Go."""
    share = round(DISK_FREE_MIN_SHARE * (resources.disk_total_bytes or 0))
    return max(DISK_FREE_MIN, min(DISK_FREE_MAX, share))


def data_limits(resources: Resources) -> tuple[int | None, int | None]:
    """Taille des données à laquelle chaque alerte du disque partirait, si elles seules
    remplissaient le disque : (presque plein, sauvegarde). Un octet de données de plus est un
    octet libre de moins ; pour la sauvegarde, il compte aussi deux fois dans la place qu'elle
    demande (base et graphe copiés), d'où le tiers."""
    used, free = resources.disk_used_bytes, resources.disk_free_bytes
    if used is None or free is None or resources.disk_total_bytes is None:
        return None, None
    full = used + free - disk_low_free(resources)
    backup = resources.disk_backup_bytes
    return full, (used + round((free - backup) / 3) if backup else None)


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
    disk_used_bytes: int | None = None  # dernière mesure du dossier des données
    written_bytes: int | None = None  # octets écrits sur disque pendant la minute


def history(samples: list[Sample]) -> list[ResourcePoint]:
    """Courbes des dernières 24 h d'après les relevés (les plus anciens d'abord) ; le premier
    relevé n'a pas de charge, faute de minute avant lui. Le dossier des données, mesuré moins
    souvent, garde sa dernière mesure entre deux : une courbe en marches, sans trous."""
    points = []
    previous: Sample | None = None
    used: int | None = None
    for sample in samples:
        used = sample.disk_used if sample.disk_used is not None else used
        if sample.time is not None:
            points.append(
                ResourcePoint(
                    time=sample.time,
                    cpu_percent=cpu_percent(previous, sample) if previous else None,
                    memory_bytes=sample.memory,
                    disk_free_bytes=sample.disk_free,
                    disk_used_bytes=used,
                    written_bytes=written_between(previous, sample) if previous else None,
                )
            )
        previous = sample
    return points


class ResourceHour(BaseModel):
    """Résumé d'une heure (UTC) : charge moyenne et plus haute, mémoire, espace libre minimal."""

    hour: datetime
    samples: int
    cpu_avg: float | None = None
    cpu_max: float | None = None
    memory_min: int | None = None
    memory_avg: int | None = None
    memory_max: int | None = None
    disk_free_min: int | None = None
    disk_used_max: int | None = None  # dossier des données, plus haute mesure de l'heure
    written_bytes: int | None = None  # octets écrits sur disque pendant l'heure (minutes relevées)


def _text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(TIME_FORMAT)


def _moment(text: str) -> datetime:
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=UTC)


class ResourceStore:
    """Minutes (24 h) et résumés horaires (30 jours) en base. Chaque minute enregistrée refait le
    résumé de son heure et retire ce qui a passé sa durée de garde, dans une même transaction."""

    def __init__(self, database: sqlite3.Connection) -> None:
        self._database = database

    def save(self, point: ResourcePoint) -> None:
        moment = point.time.astimezone(UTC)
        hour = moment.replace(minute=0, second=0, microsecond=0)
        with self._database:
            self._database.execute(
                "INSERT INTO resource_minutes (time, cpu_percent, memory_bytes, "
                "disk_free_bytes, disk_used_bytes, written_bytes) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(time) DO UPDATE SET cpu_percent = excluded.cpu_percent, "
                "memory_bytes = excluded.memory_bytes, disk_free_bytes = excluded.disk_free_bytes, "
                "disk_used_bytes = excluded.disk_used_bytes, "
                "written_bytes = excluded.written_bytes",
                (
                    _text(moment),
                    point.cpu_percent,
                    point.memory_bytes,
                    point.disk_free_bytes,
                    point.disk_used_bytes,
                    point.written_bytes,
                ),
            )
            self._database.execute(
                "INSERT INTO resource_hours (hour, samples, cpu_avg, cpu_max, memory_min, "
                "memory_avg, memory_max, disk_free_min, disk_used_max, written_bytes) "
                "SELECT ?, COUNT(*), AVG(cpu_percent), MAX(cpu_percent), MIN(memory_bytes), "
                "CAST(AVG(memory_bytes) AS INTEGER), MAX(memory_bytes), MIN(disk_free_bytes), "
                "MAX(disk_used_bytes), SUM(written_bytes) "
                "FROM resource_minutes WHERE time >= ? AND time < ? "
                "ON CONFLICT(hour) DO UPDATE SET samples = excluded.samples, "
                "cpu_avg = excluded.cpu_avg, cpu_max = excluded.cpu_max, "
                "memory_min = excluded.memory_min, memory_avg = excluded.memory_avg, "
                "memory_max = excluded.memory_max, disk_free_min = excluded.disk_free_min, "
                "disk_used_max = excluded.disk_used_max, written_bytes = excluded.written_bytes",
                (_text(hour), _text(hour), _text(hour + timedelta(hours=1))),
            )
            self._database.execute(
                "DELETE FROM resource_minutes WHERE time < ?",
                (_text(moment - timedelta(seconds=HISTORY_S)),),
            )
            self._database.execute(
                "DELETE FROM resource_hours WHERE hour < ?", (_text(moment - HOURS_KEPT),)
            )

    def minutes(self, since: datetime) -> list[ResourcePoint]:
        rows = self._database.execute(
            "SELECT time, cpu_percent, memory_bytes, disk_free_bytes, disk_used_bytes, "
            "written_bytes FROM resource_minutes WHERE time >= ? ORDER BY time",
            (_text(since),),
        ).fetchall()
        return [
            ResourcePoint(
                time=_moment(row[0]),
                cpu_percent=row[1],
                memory_bytes=row[2],
                disk_free_bytes=row[3],
                disk_used_bytes=row[4],
                written_bytes=row[5],
            )
            for row in rows
        ]

    def hours(self, since: datetime) -> list[ResourceHour]:
        rows = self._database.execute(
            "SELECT hour, samples, cpu_avg, cpu_max, memory_min, memory_avg, memory_max, "
            "disk_free_min, disk_used_max, written_bytes FROM resource_hours "
            "WHERE hour >= ? ORDER BY hour",
            (_text(since),),
        ).fetchall()
        return [
            ResourceHour(
                hour=_moment(row[0]),
                samples=row[1],
                cpu_avg=row[2],
                cpu_max=row[3],
                memory_min=row[4],
                memory_avg=row[5],
                memory_max=row[6],
                disk_free_min=row[7],
                disk_used_max=row[8],
                written_bytes=row[9],
            )
            for row in rows
        ]


def _free(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _sample(data_dir: Path | None = None, disk_used: int | None = None) -> Sample:
    return Sample(
        at=time.monotonic(),
        cpu_s=time.process_time(),
        memory=memory_bytes(),
        disk_free=_free(data_dir) if data_dir is not None else None,
        time=datetime.now(UTC),
        disk_used=disk_used,
        written=disk_written_bytes(),
    )


class ResourceMonitor:
    """Relève le processeur, la mémoire et l'espace libre toutes les minutes, le dossier des
    données toutes les 10 minutes ; ``snapshot`` y ajoute le dossier des données et les limites
    (à appeler hors de la boucle d'événements : il parcourt ce dossier). Avec une base, chaque
    minute y est gardée, et les minutes des dernières 24 h d'avant le démarrage complètent
    courbes et pics."""

    def __init__(self, data_dir: Path, database: sqlite3.Connection | None = None) -> None:
        self._data_dir = data_dir
        self._store = ResourceStore(database) if database is not None else None
        self._samples: deque[Sample] = deque(maxlen=HISTORY_S // INTERVAL_S + 1)
        start = _sample(data_dir)
        self._samples.append(start)  # point de départ de la première moyenne
        self._before: list[ResourcePoint] = []  # minutes gardées d'avant le démarrage
        if self._store is not None and start.time is not None:
            try:
                self._before = self._store.minutes(start.time - timedelta(seconds=HISTORY_S))
            except sqlite3.Error:
                logger.exception("Lecture des ressources gardées impossible")
        self._task: asyncio.Task[None] | None = None
        self._measured_at: float | None = None  # dernière mesure du dossier des données

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def record(self, sample: Sample) -> None:
        self._samples.append(sample)

    def save_last(self) -> None:
        """Garde en base la dernière minute écoulée (à appeler hors de la boucle d'événements)."""
        if self._store is None or len(self._samples) < 2:
            return
        self._store.save(history(list(self._samples))[-1])

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(INTERVAL_S)
            try:
                self.record(_sample(self._data_dir, await self._data_size()))
                await asyncio.to_thread(self.save_last)
            except Exception:  # nouvel essai à la minute suivante
                logger.exception("Relevé des ressources impossible")

    def _kept(self, now: datetime) -> list[ResourcePoint]:
        since = now - timedelta(seconds=HISTORY_S)
        return [p for p in self._before if p.time >= since]

    async def _data_size(self) -> int | None:
        """Taille du dossier des données, une fois toutes les 10 minutes (sinon None), mesurée
        hors de la boucle d'événements."""
        now = time.monotonic()
        if self._measured_at is not None and now - self._measured_at < DATA_SIZE_INTERVAL_S:
            return None
        self._measured_at = now
        return await asyncio.to_thread(directory_size, self._data_dir)

    def history(self) -> list[ResourcePoint]:
        return [*self._kept(datetime.now(UTC)), *history(list(self._samples))]

    def hours(self, days: int = 30) -> list[ResourceHour]:
        if self._store is None:
            return []
        return self._store.hours(datetime.now(UTC) - timedelta(days=days))

    def snapshot(self, now: Sample | None = None) -> Resources:
        current = now or _sample()
        moment = current.time or datetime.now(UTC)
        found = summarize(list(self._samples), current)
        # Minutes d'avant le démarrage : pics et durée couverte sur les dernières 24 h.
        kept = self._kept(moment)
        if kept:
            cpus = [p.cpu_percent for p in kept if p.cpu_percent is not None]
            memories = [p.memory_bytes for p in kept if p.memory_bytes is not None]
            if found.cpu_peak_percent is not None:
                cpus.append(found.cpu_peak_percent)
            if found.memory_peak_bytes is not None:
                memories.append(found.memory_peak_bytes)
            found.cpu_peak_percent = max(cpus, default=None)
            found.memory_peak_bytes = max(memories, default=None)
            found.measured_s = round((moment - kept[0].time).total_seconds())
        # Écritures des dernières 24 h : minutes d'avant le démarrage et relevés depuis.
        since = moment - timedelta(seconds=HISTORY_S)
        written = [
            p.written_bytes
            for p in [*kept, *history(list(self._samples))]
            if p.written_bytes is not None and p.time >= since
        ]
        found.written_day_bytes = sum(written) if written else None
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
        if found.disk_total_bytes is not None and found.disk_alert_free_bytes is not None:
            found.disk_alert_used_bytes = found.disk_total_bytes - found.disk_alert_free_bytes
        limits = [limit for limit in data_limits(found) if limit is not None]
        found.disk_alert_data_bytes = min(limits, default=None)
        return found
