"""Banc de performance du stockage (lot 0.5).

    python -m bench.run --profile quick                   # CI : quelques minutes
    python -m bench.run --profile full                    # poste, LXC, Raspberry Pi
    python -m bench.run --server http://localhost:7878    # serveur Oxigraph au lieu de pyoxigraph

Résultats affichés en tableau et écrits en JSON (``--output``). Avec ``--thresholds``, le banc
échoue si une requête dépasse son seuil (CI).
"""

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from itertools import islice
from pathlib import Path

from bench.backends import Backend, EmbeddedBackend, ServerBackend, memory_mb, peak_memory_mb
from bench.data import aggregate_nquads, day_start, raw_nquads
from bench.model import SOSA, Kind, build_home, home_nquads
from bench.organizations import (
    Query,
    agg_graph,
    partitioned_queries,
    raw_graph,
    single_queries,
)

V1_INTERVALS = {Kind.POWER: 600, Kind.ENERGY: 600, Kind.MEASUREMENT: 600}
REALTIME_INTERVALS = {Kind.POWER: 15, Kind.ENERGY: 60, Kind.MEASUREMENT: 300}


@dataclass(frozen=True)
class Profile:
    single_days: int  # historique de l'organisation v1
    raw_days: int  # relevés bruts en temps réel gardés
    quarter_days: int  # agrégats au quart d'heure gardés
    hour_days: int  # agrégats horaires gardés
    runs: int  # exécutions de chaque requête (médiane)
    sensors: tuple[int, int, int] = (40, 60, 60)  # capteurs de puissance, d'énergie, autres


PROFILES = {
    "quick": Profile(single_days=63, raw_days=1, quarter_days=31, hour_days=90, runs=3),
    "full": Profile(single_days=63, raw_days=3, quarter_days=35, hour_days=365, runs=5),
    # Tests : quelques secondes, pour vérifier que tout s'enchaîne et que les requêtes répondent.
    "tiny": Profile(
        single_days=3, raw_days=1, quarter_days=2, hour_days=3, runs=1, sensors=(8, 10, 1)
    ),
}


@dataclass
class Result:
    backend: str
    profile: str
    machine: str
    loads: dict[str, dict[str, float]] = field(default_factory=dict)
    queries: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    ingestion: dict[str, float] = field(default_factory=dict)
    retention: dict[str, float] = field(default_factory=dict)
    sizes_mb: dict[str, float | None] = field(default_factory=dict)
    peak_memory_mb: float | None = None
    memory_by_phase_mb: dict[str, float] = field(default_factory=dict)


def note_memory(result: "Result", phase: str) -> None:
    """Mémoire actuelle après une phase (localise les pics)."""
    memory = memory_mb()
    if memory:
        result.memory_by_phase_mb[phase] = round(memory[0])
        print(f"  mémoire après « {phase} » : {memory[0]:.0f} Mo (pic {memory[1]:.0f} Mo)")


def timed(action: Callable[[], object]) -> float:
    start = time.perf_counter()
    action()
    return time.perf_counter() - start


# Taille des morceaux chargés en masse : borne la mémoire du banc (une journée de relevés en
# temps réel fait 2 millions de triplets, près de 3 Go en mémoire si elle est chargée d'un coup).
CHUNK_TRIPLES = 200_000


def chunks(lines: Iterator[str], size: int = CHUNK_TRIPLES) -> Iterator[tuple[bytes, int]]:
    while True:
        part = list(islice(lines, size))
        if not part:
            return
        yield "".join(part).encode(), len(part)


def load_days(
    backend: Backend, days: range, lines: Callable[[int], Iterator[str]]
) -> dict[str, float]:
    triples, seconds = 0, 0.0
    for day in days:
        for data, count in chunks(lines(day)):
            seconds += timed(lambda data=data: backend.load(data, bulk=True))
            triples += count
    return {
        "triples": triples,
        "seconds": round(seconds, 2),
        "triples_per_s": round(triples / seconds),
    }


def measure_queries(
    backend: Backend, queries: list[Query], runs: int
) -> dict[str, dict[str, float]]:
    results = {}
    for query in queries:
        rows = backend.query(query.sparql)  # échauffement
        durations = [timed(lambda q=query: backend.query(q.sparql)) for _ in range(runs)]
        results[query.name] = {"rows": rows, "median_s": round(statistics.median(durations), 4)}
        print(f"  {query.name:<15} {results[query.name]['median_s']:>8.4f} s  {rows:>7} lignes")
    return results


def run(profile_name: str, make_backend: Callable[[str], Backend]) -> Result:
    profile = PROFILES[profile_name]
    sensors = build_home(*profile.sensors)
    today = max(profile.single_days, profile.hour_days) - 1
    single = make_backend("single")
    result = Result(
        backend=single.name,
        profile=profile_name,
        machine=f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
    )

    # --- Organisation v1 : tout dans le graphe par défaut, relevé toutes les 10 min ------------
    print("Organisation « single » (v1)")
    single.load(home_nquads(sensors).encode(), bulk=True)
    days = range(today + 1 - profile.single_days, today + 1)
    result.loads["single"] = load_days(
        single, days, lambda d: raw_nquads(sensors, d, V1_INTERVALS, None)
    )
    note_memory(result, "chargement v1")
    result.queries["single"] = measure_queries(single, single_queries(sensors, today), profile.runs)
    note_memory(result, "requêtes v1")
    result.sizes_mb["single"] = _mb(single.size_bytes())
    single.close()

    # --- Organisation partitionnée : brut temps réel + agrégats ---------------------------------
    print("Organisation « partitioned »")
    part = make_backend("partitioned")
    part.load(home_nquads(sensors).encode(), bulk=True)
    raw_days = range(today + 1 - profile.raw_days, today + 1)
    result.loads["raw"] = load_days(
        part,
        raw_days,
        lambda d: raw_nquads(sensors, d, REALTIME_INTERVALS, raw_graph(day_start(d))),
    )
    note_memory(result, "chargement brut")
    quarter_days = range(today + 1 - profile.quarter_days, today + 1)
    result.loads["quarter"] = load_days(
        part,
        quarter_days,
        lambda d: aggregate_nquads(sensors, d, 900, lambda t: agg_graph("PT15M", t)),
    )
    hour_days = range(today + 1 - profile.hour_days, today + 1)
    result.loads["hour"] = load_days(
        part,
        hour_days,
        lambda d: aggregate_nquads(sensors, d, 3600, lambda t: agg_graph("PT1H", t)),
    )
    note_memory(result, "chargement agrégats")
    result.queries["partitioned"] = measure_queries(
        part, partitioned_queries(sensors, today), profile.runs
    )
    note_memory(result, "requêtes partitionnées")
    result.sizes_mb["partitioned"] = _mb(part.size_bytes())

    # Ingestion en temps réel : une heure de relevés, par lots d'une minute (une transaction par
    # lot, volume moyen d'une minute de la journée).
    observations_per_day = sum(86400 // REALTIME_INTERVALS[sensor.kind] for sensor in sensors)
    triples_per_day = observations_per_day * 6
    batch_size = triples_per_day // (24 * 60)
    stream = raw_nquads(sensors, today + 1, REALTIME_INTERVALS, raw_graph(day_start(today + 1)))
    batches = ["".join(islice(stream, batch_size)).encode() for _ in range(60)]
    batch_times = [timed(lambda b=batch: part.load(b, bulk=False)) for batch in batches]
    result.ingestion = {
        "observations_per_day": observations_per_day,
        "triples_per_day": triples_per_day,
        "batch_triples": batch_size,
        "batch_median_s": round(statistics.median(batch_times), 4),
        "batch_max_s": round(max(batch_times), 4),
    }
    print(
        f"  ingestion : lot d'une minute ({batch_size} triplets) "
        f"en {result.ingestion['batch_median_s']} s (médiane)"
    )
    note_memory(result, "ingestion")

    # Durée de conservation : suppression d'une journée de relevés bruts.
    oldest = raw_graph(day_start(raw_days.start))

    # Capteur par capteur, avec un flush entre chaque : supprimer les 2 millions de triplets
    # d'un coup (remove_graph, une seule transaction) montait à 2,8 Go de mémoire.
    def remove_day() -> None:
        for sensor in sensors:
            part.update(
                f"DELETE WHERE {{ GRAPH <{oldest}> {{ "
                f"?o <{SOSA}madeBySensor> <{sensor.iri}> ; ?p ?v }} }}"
            )
            part.flush()

    result.retention["remove_raw_day_s"] = round(timed(remove_day), 3)
    note_memory(result, "suppression d'une journée")
    part.close()

    result.peak_memory_mb = peak_memory_mb()
    return result


def _mb(size: int | None) -> float | None:
    return None if size is None else round(size / 1_048_576, 1)


def check_thresholds(result: Result, thresholds: dict[str, float]) -> list[str]:
    failures = []
    for name, values in result.queries["partitioned"].items():
        limit = thresholds.get(name)
        if limit is not None and values["median_s"] > limit:
            failures.append(f"{name} : {values['median_s']} s > {limit} s")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument("--server", help="URL d'un serveur Oxigraph (sinon pyoxigraph)")
    parser.add_argument("--data-dir", type=Path, help="dossier des magasins (temporaire sinon)")
    parser.add_argument("--output", type=Path, help="fichier JSON des résultats")
    parser.add_argument("--thresholds", type=Path, help="seuils JSON {requête: secondes}")
    args = parser.parse_args()

    base = args.data_dir or Path(tempfile.mkdtemp(prefix="wattslot-bench-"))

    def make_backend(name: str) -> Backend:
        if args.server:
            return ServerBackend(args.server)
        return EmbeddedBackend(base / name)

    started = time.perf_counter()
    result = run(args.profile, make_backend)
    print(f"Durée totale : {time.perf_counter() - started:.0f} s")
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    if args.output:
        args.output.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), "utf-8")
    if args.thresholds:
        failures = check_thresholds(result, json.loads(args.thresholds.read_text("utf-8")))
        for failure in failures:
            print(f"SEUIL DÉPASSÉ  {failure}", file=sys.stderr)
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
