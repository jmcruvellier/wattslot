"""Banc des écritures disque de l'ingestion : octets réellement écrits par le processus.

    python dev/tools/bench_writes.py [--hours 2] [--per-minute 350] [--batch-s 30] [--flush-min 30]

Rejoue ``--hours`` d'ingestion au débit réel (``--per-minute`` relevés retenus, environ 350 dans
la maison de référence, soit 2 millions de triplets par jour) par lots de ``--batch-s``
secondes, dans les magasins bruts de l'application (``RawStores``), avec l'état de l'ingestion
en SQLite, et compte les octets écrits par le processus (``/proc/self/io`` sous Linux,
``GetProcessIoCounters`` sous Windows), ramenés à une journée. À lancer avec l'environnement du
backend (``app/backend/.venv``).
"""

import argparse
import ctypes
import json
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wattslot.ingestion import Ingestor
from wattslot.storage import raw as raw_module
from wattslot.storage.database import open_database
from wattslot.storage.raw import RawStores, Reading

ENTITIES = 40


def written_bytes() -> int:
    """Octets écrits par le processus depuis son démarrage."""
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in ("ro", "wo", "oo", "rb", "wb", "ob")  # opérations puis octets
            ]

        kernel = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters)]
        counters = Counters()
        kernel.GetProcessIoCounters(kernel.GetCurrentProcess(), ctypes.byref(counters))
        return int(counters.wb)
    for line in Path("/proc/self/io").read_text().splitlines():
        if line.startswith("write_bytes:"):
            return int(line.split()[1])
    raise RuntimeError("write_bytes introuvable")


def peak_memory_mb() -> float:
    """Pic de mémoire résidente du processus."""
    if sys.platform == "win32":

        class Memory(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t)
                for name in ("peak", "current", "a", "b", "c", "d", "e", "f")
            ]

        psapi = ctypes.WinDLL("psapi")  # type: ignore[attr-defined]
        kernel = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(Memory),
            ctypes.c_ulong,
        ]
        memory = Memory(cb=ctypes.sizeof(Memory))
        psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb)
        return memory.peak / 1e6
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3  # Ko sous Linux


def run(hours: float, per_minute: int, batch_s: float) -> dict[str, float]:
    # Sous Windows, le verrou de RocksDB empêche de supprimer le dossier tant que le processus vit.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        clock = [0.0]  # temps simulé : les flush à intervalle suivent le rythme réel
        raw = RawStores(root, "Europe/Paris", clock=lambda: clock[0])
        database = open_database(root)
        ingestor = Ingestor(None, raw, database)  # type: ignore[arg-type]
        start = datetime(2026, 10, 16, 8, tzinfo=UTC)
        per_batch = max(1, round(per_minute * batch_s / 60))
        batches = int(hours * 3600 / batch_s)
        before, began = written_bytes(), time.perf_counter()
        for k in range(batches):
            moment = start + timedelta(seconds=k * batch_s)
            clock[0] = k * batch_s
            batch = [
                Reading(
                    f"sensor.e{i % ENTITIES}",
                    f"http://example.org/sensor/e{i % ENTITIES}",
                    float(i),
                    moment + timedelta(milliseconds=i),
                )
                for i in range(per_batch)
            ]
            ingestor.write_batch(batch, moment)
        ingestor.close()
        written = written_bytes() - before
        seconds = time.perf_counter() - began
        raw_size = sum(p.stat().st_size for p in (root / "raw").rglob("*") if p.is_file())
        database.close()
        del raw
    per_day = written * 24 / hours
    return {
        "hours": hours,
        "readings": batches * per_batch,
        "batches": batches,
        "written_mb": round(written / 1e6, 1),
        "written_gb_per_day": round(per_day / 1e9, 2),
        "raw_size_mb": round(raw_size / 1e6, 1),
        "amplification": round(written / raw_size, 1) if raw_size else 0.0,
        "seconds": round(seconds, 1),
        "peak_memory_mb": round(peak_memory_mb()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--per-minute", type=int, default=350)
    parser.add_argument("--batch-s", type=float, default=30.0)
    parser.add_argument(
        "--flush-min", type=float, help="intervalle des flush (défaut : celui de l'application)"
    )
    args = parser.parse_args()
    if args.flush_min is not None:
        raw_module.FLUSH_INTERVAL = timedelta(minutes=args.flush_min)
    print(json.dumps(run(args.hours, args.per_minute, args.batch_s), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
