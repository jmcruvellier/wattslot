"""Relevés bruts : un magasin Oxigraph par jour (heure locale de la maison).

Exigence issue du banc du lot 0.5 (``bench/``) : supprimer une journée de
relevés par requêtes prenait 28 minutes sur un Intel N150 ; avec un magasin par jour, c'est la
suppression d'un dossier (lot 1.4).

Écritures par lots (une transaction, consignée dans le journal de RocksDB), mais ``flush``
espacés : chaque ``flush`` crée de petits fichiers sur disque que RocksDB recompacte ensuite, et
un ``flush`` toutes les 5 s faisait écrire au processus 37 fois le volume stocké (5 à 7 Go par
jour dans le LXC, ``dev/tools/bench_writes.py``). Le ``flush`` borne la mémoire de RocksDB (règle
du banc) : il a lieu après ``FLUSH_TRIPLES`` triplets écrits dans un magasin ou au
bout de ``FLUSH_INTERVAL``, et toujours à la fermeture. Banc d'une journée simulée : 2 Go écrits
par jour et 116 Mo de mémoire au plus avec un flush par heure (1,4 Go et 218 Mo toutes les 4 h).

Modèle RDF (SOSA, comme la v1, allégé : propriété et objet observés se déduisent du capteur dans
le modèle de la maison) ::

    <obs> a sosa:Observation ;
        sosa:madeBySensor <capteur du modèle de la maison> ;
        sosa:resultTime "…Z"^^xsd:dateTime ;
        sosa:hasSimpleResult "…"^^xsd:double .
"""

import shutil
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyoxigraph

from wattslot.detection import slug
from wattslot.ontology import HOME

RAW_DIRNAME = "raw"
# Journées conservées (3) et aujourd'hui : l'agrégation relit les jours précédents pendant que
# l'ingestion écrit aujourd'hui ; un magasin fermé puis rouvert pendant qu'un autre fil s'en
# sert serait verrouillé par RocksDB.
OPEN_STORES = 5
FLUSH_TRIPLES = 200_000  # triplets écrits dans un magasin avant son flush
FLUSH_INTERVAL = timedelta(minutes=60)

SOSA = "http://www.w3.org/ns/sosa/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
TRIPLES_PER_READING = 4


@dataclass(frozen=True)
class Reading:
    entity_id: str
    sensor_iri: str
    value: float  # unité normalisée : kWh pour l'énergie, W pour la puissance, % sinon
    time: datetime  # en UTC


def _xsd_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def reading_nquads(reading: Reading) -> str:
    epoch_ms = int(reading.time.timestamp() * 1000)
    obs = f"<{HOME}obs/{slug(reading.entity_id)}/{epoch_ms}>"
    when = _xsd_time(reading.time)
    return (
        f"{obs} <{RDF_TYPE}> <{SOSA}Observation> .\n"
        f"{obs} <{SOSA}madeBySensor> <{reading.sensor_iri}> .\n"
        f'{obs} <{SOSA}resultTime> "{when}"^^<{XSD}dateTime> .\n'
        f'{obs} <{SOSA}hasSimpleResult> "{reading.value!r}"^^<{XSD}double> .\n'
    )


class RawStores:
    def __init__(
        self,
        data_dir: Path,
        time_zone: str = "UTC",
        clock: Callable[[], float] = time.monotonic,  # secondes ; simulée par le banc
    ) -> None:
        self.root = data_dir / RAW_DIRNAME
        self.root.mkdir(parents=True, exist_ok=True)
        self.zone = ZoneInfo(time_zone)
        self._open: OrderedDict[date, pyoxigraph.Store] = OrderedDict()
        self._lock = threading.Lock()  # écriture (ingestion) et lecture (agrégation)
        self._unflushed: dict[date, int] = {}  # triplets écrits depuis le dernier flush
        self._clock = clock
        self._flushed_at = clock()

    def set_time_zone(self, time_zone: str) -> None:
        self.zone = ZoneInfo(time_zone)

    def day_of(self, moment: datetime) -> date:
        return moment.astimezone(self.zone).date()

    def days(self) -> list[date]:
        return sorted(date.fromisoformat(p.name) for p in self.root.iterdir() if p.is_dir())

    def store(self, day: date) -> pyoxigraph.Store:
        with self._lock:
            if day in self._open:
                self._open.move_to_end(day)
                return self._open[day]
            store = pyoxigraph.Store(str(self.root / day.isoformat()))
            self._open[day] = store
            while len(self._open) > OPEN_STORES:
                day_out, oldest = self._open.popitem(last=False)
                oldest.flush()
                self._unflushed.pop(day_out, None)
            return store

    def write(self, readings: Iterable[Reading]) -> int:
        """Écrit un lot (une transaction par jour), ``flush`` selon le volume et le temps écoulé ;
        renvoie les relevés écrits."""
        by_day: dict[date, list[str]] = {}
        for reading in readings:
            by_day.setdefault(self.day_of(reading.time), []).append(reading_nquads(reading))
        written = 0
        for day, lines in sorted(by_day.items()):
            store = self.store(day)
            store.load("".join(lines).encode(), format=pyoxigraph.RdfFormat.N_QUADS)
            self._unflushed[day] = self._unflushed.get(day, 0) + TRIPLES_PER_READING * len(lines)
            if self._unflushed[day] >= FLUSH_TRIPLES:
                store.flush()
                self._unflushed[day] = 0
            written += len(lines)
        if self._clock() - self._flushed_at >= FLUSH_INTERVAL.total_seconds():
            self.flush()
        return written

    def count(self, day: date) -> int:
        """Nombre d'observations d'une journée."""
        solutions = self.store(day).query(
            f"SELECT (COUNT(?o) AS ?n) WHERE {{ ?o a <{SOSA}Observation> }}"
        )
        assert isinstance(solutions, pyoxigraph.QuerySolutions)
        for solution in solutions:
            return int(solution["n"].value)
        return 0

    def readings(self, start: datetime, end: datetime) -> list[tuple[str, datetime, float]]:
        """Relevés de ``[start, end)``, tous capteurs : (IRI du capteur, heure UTC, valeur)."""
        found: list[tuple[str, datetime, float]] = []
        first, last = self.day_of(start), self.day_of(end - timedelta(microseconds=1))
        bounds = (
            f'FILTER(?t >= "{_xsd_time(start)}"^^<{XSD}dateTime> && '
            f'?t < "{_xsd_time(end)}"^^<{XSD}dateTime>)'
        )
        for day in self.days():
            if not first <= day <= last:
                continue
            solutions = self.store(day).query(
                f"SELECT ?s ?t ?v WHERE {{ ?o <{SOSA}madeBySensor> ?s ; "
                f"<{SOSA}resultTime> ?t ; <{SOSA}hasSimpleResult> ?v . {bounds} }}"
            )
            assert isinstance(solutions, pyoxigraph.QuerySolutions)
            for solution in solutions:
                time = datetime.fromisoformat(solution["t"].value).astimezone(UTC)
                found.append((solution["s"].value, time, float(solution["v"].value)))
        return found

    def counts_by_sensor(self, day: date) -> dict[str, int]:
        """Observations d'une journée par capteur (sans créer le magasin s'il n'existe pas)."""
        if day not in self.days():
            return {}
        solutions = self.store(day).query(
            f"SELECT ?s (COUNT(?o) AS ?n) WHERE {{ ?o <{SOSA}madeBySensor> ?s }} GROUP BY ?s"
        )
        assert isinstance(solutions, pyoxigraph.QuerySolutions)
        return {solution["s"].value: int(solution["n"].value) for solution in solutions}

    def remove_day(self, day: date) -> None:
        """Supprime une journée : un dossier (utilisé par la conservation, lot 1.4)."""
        with self._lock:
            store = self._open.pop(day, None)
            self._unflushed.pop(day, None)
        if store is not None:
            store.flush()
            del store
        shutil.rmtree(self.root / day.isoformat(), ignore_errors=True)

    def flush(self) -> None:
        """Vide sur disque ce qui a été écrit depuis le dernier ``flush`` (arrêt, intervalle)."""
        for day, store in list(self._open.items()):
            if self._unflushed.get(day):
                store.flush()
            self._unflushed[day] = 0
        self._flushed_at = self._clock()
