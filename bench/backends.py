"""Les deux intégrations d'Oxigraph comparées.

- ``EmbeddedBackend`` : bibliothèque ``pyoxigraph`` dans le processus (choix du lot 0.2) ;
- ``ServerBackend`` : serveur Oxigraph joint en HTTP (point SPARQL et protocole Graph Store).
"""

import json
import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

import pyoxigraph


class Backend(Protocol):
    name: str

    def load(self, nquads: bytes, *, bulk: bool) -> None: ...
    def query(self, sparql: str) -> int: ...
    def remove_graph(self, graph: str) -> None: ...
    def update(self, sparql: str) -> None: ...
    def flush(self) -> None: ...
    def size_bytes(self) -> int | None: ...
    def close(self) -> None: ...


class EmbeddedBackend:
    name = "pyoxigraph"

    def __init__(self, path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        self._path = path
        self._store = pyoxigraph.Store(str(path))

    def load(self, nquads: bytes, *, bulk: bool) -> None:
        if bulk:
            self._store.bulk_load(nquads, format=pyoxigraph.RdfFormat.N_QUADS)
        else:
            self._store.load(nquads, format=pyoxigraph.RdfFormat.N_QUADS)

    def query(self, sparql: str) -> int:
        return sum(1 for _ in self._store.query(sparql))

    def remove_graph(self, graph: str) -> None:
        self._store.remove_graph(pyoxigraph.NamedNode(graph))

    def update(self, sparql: str) -> None:
        self._store.update(sparql)

    def flush(self) -> None:
        self._store.flush()

    def size_bytes(self) -> int:
        self._store.flush()
        return sum(f.stat().st_size for f in self._path.rglob("*") if f.is_file())

    def close(self) -> None:
        self._store.flush()


class ServerBackend:
    name = "serveur"

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._request("POST", "/update", b"CLEAR ALL", "application/sparql-update")

    def _request(self, method: str, path: str, body: bytes | None, content_type: str) -> bytes:
        headers = {"Content-Type": content_type, "Accept": "application/sparql-results+json"}
        req = urllib.request.Request(self._url + path, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=600) as response:
            return bytes(response.read())

    def load(self, nquads: bytes, *, bulk: bool) -> None:
        path = "/store?no_transaction" if bulk else "/store"
        self._request("POST", path, nquads, "application/n-quads")

    def query(self, sparql: str) -> int:
        body = self._request("POST", "/query", sparql.encode(), "application/sparql-query")
        return len(json.loads(body)["results"]["bindings"])

    def remove_graph(self, graph: str) -> None:
        self._request(
            "DELETE", "/store?graph=" + urllib.parse.quote(graph, safe=""), None, "text/plain"
        )

    def update(self, sparql: str) -> None:
        self._request("POST", "/update", sparql.encode(), "application/sparql-update")

    def flush(self) -> None:
        pass

    def size_bytes(self) -> None:
        return None

    def close(self) -> None:
        pass


def memory_mb() -> tuple[float, float] | None:
    """Mémoire du processus : (actuelle, maximale) en Mo, sous Linux et Windows."""
    status = Path("/proc/self/status")
    if status.exists():
        values = {}
        for line in status.read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("VmRSS", "VmHWM"):
                values[key] = int(rest.split()[0]) / 1024
        if len(values) == 2:
            return values["VmRSS"], values["VmHWM"]
        return None
    if os.name == "nt":
        return _windows_memory_mb()
    return None


def peak_memory_mb() -> float | None:
    memory = memory_mb()
    return memory[1] if memory else None


def _windows_memory_mb() -> tuple[float, float]:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.WorkingSetSize / 1048576, counters.PeakWorkingSetSize / 1048576
