"""Détail de la mémoire du processus, et mémoire libre rendue au système (Linux, glibc).

La mémoire résidente seule ne dit pas ce qui la tient. Sur une installation réelle, elle montait
par paliers à chaque gros travail (calcul du plan, contrôle de la qualité, longue lecture par
l'API) sans redescendre, alors qu'aucune structure de l'application ne grossissait : lectures du
graphe, solveur et boucles de fond mesurés stables (12/11/2026). Hypothèse : la mémoire libérée
par l'application reste gardée par l'allocateur de glibc, qui ne rend au système que le haut de
chaque tas, et tient un tas par fil.

``detail`` sépare donc ce que le processus utilise de ce que l'allocateur garde libre, et compte
ce qui peut fuir par ailleurs (fils, fichiers ouverts). ``release`` rend la mémoire libre au
système (``malloc_trim``) après chaque calcul du plan, et écrit dans le journal ce que cela a
rendu : une baisse nette confirme l'hypothèse, une baisse nulle la réfute.

La mémoire « utilisée » de glibc mêle les objets Python et la mémoire native (RocksDB). Elle montait
encore d'environ 80 Mo par jour sur une installation réelle (palier pendant la maintenance de la
nuit, lente dérive en journée, 15/11/2026) : le journal compte donc aussi les blocs alloués par
Python, les objets suivis par le ramasse-miettes et les types dont le nombre a le plus augmenté
depuis le calcul précédent. Des chiffres Python plats pendant la hausse la placent côté natif.

Les chiffres Python sont restés plats pendant une hausse native d'environ 50 Mo par jour
(17/11/2026). Pour savoir si elle vient du calcul (solveur, lectures) ou de ce qui tourne entre
deux calculs (ingestion, agrégation), le journal sépare aussi la mémoire utilisée gagnée entre deux
calculs de celle gagnée pendant le calcul (``heap_used`` relevé juste avant le calcul).

Hors de Linux, ou avec une autre bibliothèque C que glibc, tout est inconnu (``None``) et
``release`` ne fait rien.
"""

import ctypes
import gc
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

GROWTH_TYPES = 5  # types d'objets Python en plus forte hausse écrits dans le journal
PROC_STATUS = Path("/proc/self/status")
PROC_FD = Path("/proc/self/fd")
# Champs de /proc/self/status, en kilo-octets sauf le nombre de fils.
STATUS_FIELDS = {
    "VmRSS": "resident_bytes",
    "RssAnon": "anonymous_bytes",
    "RssFile": "file_bytes",
    "VmSwap": "swap_bytes",
    "Threads": "threads",
}


class MemoryDetail(BaseModel):
    """Ce qui compose la mémoire du processus ; ``None`` : inconnu sur ce système."""

    resident_bytes: int | None = None  # mémoire résidente (celle des courbes)
    anonymous_bytes: int | None = None  # allouée par le processus (tas, piles)
    file_bytes: int | None = None  # fichiers projetés en mémoire (bibliothèques)
    swap_bytes: int | None = None  # pages du processus mises en échange par le système
    threads: int | None = None
    open_files: int | None = None  # descripteurs ouverts (fichiers, connexions)
    database_connections: int | None = None  # connexions SQLite ouvertes, une par fil
    # Allocateur de glibc, tous tas confondus (``mallinfo2``).
    heap_used_bytes: int | None = None  # alloué et utilisé par l'application
    heap_free_bytes: int | None = None  # libéré par l'application, gardé par l'allocateur
    heap_mapped_bytes: int | None = None  # grands blocs, rendus au système dès leur libération
    python_blocks: int | None = None  # blocs alloués par Python (``sys.getallocatedblocks``)


class _Mallinfo2(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_size_t)
        for name in (
            "arena",
            "ordblks",
            "smblks",
            "hblks",
            "hblkhd",
            "usmblks",
            "fsmblks",
            "uordblks",
            "fordblks",
            "keepcost",
        )
    ]


def status_fields(proc_status: str) -> dict[str, int]:
    """Champs utiles du contenu de ``/proc/self/status``, en octets (le nombre de fils tel
    quel)."""
    found: dict[str, int] = {}
    for line in proc_status.splitlines():
        name, _, value = line.partition(":")
        field = STATUS_FIELDS.get(name)
        parts = value.split()
        if field is None or not parts or not parts[0].isdigit():
            continue
        found[field] = int(parts[0]) * (1 if field == "threads" else 1024)
    return found


def _libc() -> ctypes.CDLL | None:
    """Bibliothèque C du processus, sous Linux seulement."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        return ctypes.CDLL(None)
    except OSError:
        return None


def _heap() -> dict[str, int]:
    """État de l'allocateur ; vide sans ``mallinfo2`` (glibc d'avant 2.33, autre bibliothèque)."""
    libc = _libc()
    mallinfo2 = getattr(libc, "mallinfo2", None) if libc is not None else None
    if mallinfo2 is None:
        return {}
    mallinfo2.restype = _Mallinfo2
    info = mallinfo2()
    return {
        "heap_used_bytes": int(info.uordblks),
        "heap_free_bytes": int(info.fordblks),
        "heap_mapped_bytes": int(info.hblkhd),
    }


def _open_files() -> int | None:
    try:
        return len(os.listdir(PROC_FD))
    except OSError:
        return None


def heap_used() -> int | None:
    """Mémoire utilisée par l'application d'après l'allocateur ; ``None`` sans ``mallinfo2``.
    Assez légère pour être relevée juste avant chaque calcul."""
    return _heap().get("heap_used_bytes")


def _python_blocks() -> int:
    return sys.getallocatedblocks()


def object_types() -> Counter[str]:
    """Nombre d'objets suivis par le ramasse-miettes, par type (quelques dixièmes de seconde
    pour quelques centaines de milliers d'objets : une fois par calcul, pas à chaque relevé)."""
    found: Counter[str] = Counter()
    for item in gc.get_objects():
        kind = type(item)
        module = kind.__module__
        found[kind.__qualname__ if module == "builtins" else f"{module}.{kind.__qualname__}"] += 1
    return found


def growth(
    previous: Counter[str], current: Counter[str], limit: int = GROWTH_TYPES
) -> list[tuple[str, int]]:
    """Types dont le nombre d'objets a le plus augmenté, du plus fort au plus faible."""
    found = [(name, count - previous[name]) for name, count in current.items()]
    return sorted((item for item in found if item[1] > 0), key=lambda item: (-item[1], item[0]))[
        :limit
    ]


_previous_types: Counter[str] | None = None  # relevé du calcul précédent
_previous_used: int | None = None  # mémoire utilisée après le calcul précédent


def _gain(value: int | None, base: int | None) -> str:
    return "?" if value is None or base is None else f"{(value - base) / 1e6:+.0f}"


def _phases(used_before: int | None, used_after: int | None) -> str:
    """Mémoire utilisée gagnée entre deux calculs puis pendant ce calcul."""
    global _previous_used
    between = _gain(used_before, _previous_used)
    during = _gain(used_after, used_before)
    _previous_used = used_after
    return f"utilisée {between} Mo entre deux calculs, {during} Mo pendant le calcul"


def _python_summary() -> str:
    """Objets Python suivis, et types en plus forte hausse depuis l'appel précédent."""
    global _previous_types
    current = object_types()
    if _previous_types is None:
        rising = "premier relevé"
    else:
        found = growth(_previous_types, current)
        rising = ", ".join(f"{name} +{count}" for name, count in found) or "aucune"
    _previous_types = current
    return f"{sum(current.values())} objets suivis, hausse depuis le calcul précédent : {rising}"


def detail(database_connections: int | None = None) -> MemoryDetail:
    """Détail de la mémoire à l'instant de l'appel."""
    try:
        fields = status_fields(PROC_STATUS.read_text())
    except OSError:
        fields = {}
    return MemoryDetail(
        **fields,
        **_heap(),
        open_files=_open_files(),
        database_connections=database_connections,
        python_blocks=_python_blocks(),
    )


def trim() -> bool | None:
    """Rend au système la mémoire libre de l'allocateur (``malloc_trim``) : vrai si de la
    mémoire a été rendue, ``None`` si la fonction n'existe pas ici."""
    libc = _libc()
    malloc_trim = getattr(libc, "malloc_trim", None) if libc is not None else None
    if malloc_trim is None:
        return None
    malloc_trim.argtypes = [ctypes.c_size_t]
    malloc_trim.restype = ctypes.c_int
    return bool(malloc_trim(0))


def _megabytes(value: int | None) -> str:
    return "?" if value is None else str(round(value / 1e6))


def release(
    database_connections: int | None = None, used_before: int | None = None
) -> tuple[MemoryDetail, MemoryDetail] | None:
    """Ramasse les objets Python hors d'usage, rend la mémoire libre au système et écrit dans le
    journal l'état d'avant et d'après ; ``None`` là où ce n'est pas possible. ``used_before`` :
    mémoire utilisée relevée juste avant le calcul (``heap_used``). À appeler hors de la boucle
    d'événements."""
    before = detail(database_connections)
    gc.collect()
    if trim() is None:
        return None
    after = detail(database_connections)
    logger.info(
        "Mémoire après le calcul : %s Mo, puis %s Mo une fois la mémoire libre rendue au système "
        "(utilisée par l'application %s Mo, libre gardée par l'allocateur %s puis %s Mo, en "
        "échange %s Mo ; %s fils, %s fichiers ouverts, %s connexions à la base ; %s ; "
        "Python : %s blocs, %s)",
        _megabytes(before.resident_bytes),
        _megabytes(after.resident_bytes),
        _megabytes(after.heap_used_bytes),
        _megabytes(before.heap_free_bytes),
        _megabytes(after.heap_free_bytes),
        _megabytes(after.swap_bytes),
        "?" if after.threads is None else after.threads,
        "?" if after.open_files is None else after.open_files,
        "?" if database_connections is None else database_connections,
        _phases(used_before, after.heap_used_bytes),
        "?" if after.python_blocks is None else after.python_blocks,
        _python_summary(),
    )
    return before, after
