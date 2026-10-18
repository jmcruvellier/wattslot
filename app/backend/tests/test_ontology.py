"""Bibliothèque « Énergie domestique » et schéma de l'application (lot 2b.1) : deux fichiers, deux
graphes nommés ; chaque terme écrit ou lu par le code existe dans l'un des deux, et la
bibliothèque se suffit à elle-même."""

import re
from datetime import date
from importlib import resources
from pathlib import Path

import pyoxigraph
import pytest

from wattslot import configuration, home_model, profiles
from wattslot.battery_settings import FloorRange
from wattslot.objective_settings import ObjectiveSettings, Preset, Weights
from wattslot.ontology import (
    BASE,
    GRAPH_LIBRARY,
    GRAPH_SCHEMA,
    VOCAB,
)
from wattslot.recurrence_settings import Recurrence
from wattslot.storage.graph import GraphStore
from wattslot.time_constraints import ConstraintKind, TimeConstraint

SOURCES = Path(__file__).parents[1] / "src" / "wattslot"
FILES = {"library": "library/home-energy.ttl", "schema": "schema.ttl"}


def store(name: str) -> pyoxigraph.Store:
    found = pyoxigraph.Store()
    turtle = resources.files("wattslot.ontology").joinpath(FILES[name]).read_bytes()
    found.load(turtle, format=pyoxigraph.RdfFormat.TURTLE, base_iri=BASE)
    return found


def declared(name: str) -> set[str]:
    return {
        q.subject.value.removeprefix(VOCAB)
        for q in store(name)
        if isinstance(q.subject, pyoxigraph.NamedNode) and q.subject.value.startswith(VOCAB)
    }


def used(found: pyoxigraph.Store) -> set[str]:
    """Termes de l'espace de noms ``wattslot`` cités comme prédicat ou objet."""
    terms = set()
    for q in found:
        for node in (q.predicate, q.object):
            if isinstance(node, pyoxigraph.NamedNode) and node.value.startswith(VOCAB):
                terms.add(node.value.removeprefix(VOCAB))
    return terms


def full_configuration() -> configuration.Configuration:
    """Configuration qui écrit tous les réglages connus (profils, contraintes, objectif…)."""
    found = profiles.load("reference").configuration
    devices = [
        d.model_copy(
            update={
                "constraints": [
                    TimeConstraint(kind=ConstraintKind.FORBIDDEN, start_hour=22, end_hour=7)
                ],
                "max_delay_days": 1,
                "recurrence": Recurrence(rule="FREQ=WEEKLY;BYDAY=TU", start=date(2026, 10, 13))
                if d.key == "dishwasher"
                else d.recurrence,
            }
        )
        for d in found.devices
    ]
    battery = found.battery
    assert battery is not None
    return found.model_copy(
        update={
            "devices": devices,
            "battery": battery.model_copy(
                update={"floor_ranges": [FloorRange(start_hour=0, end_hour=6, percent=20)]}
            ),
            "objective": ObjectiveSettings(
                preset=Preset.CUSTOM,
                weights=Weights(cost=1, grid_export=1, co2=1, battery=1),
                co2_entity="sensor.co2",
            ),
        }
    )


def test_two_ontologies_one_namespace_no_term_twice() -> None:
    library, schema = declared("library"), declared("schema")

    assert library and schema and not library & schema
    imports = {q.object.value for q in store("library") if q.predicate.value.endswith("#imports")}
    assert imports == {
        "https://saref.etsi.org/core/",
        "https://saref.etsi.org/saref4ener/",
        "http://www.w3.org/ns/sosa/",
        "http://www.w3.org/ns/ssn/",
    }


def test_the_library_stands_on_its_own() -> None:
    assert used(store("library")) <= declared("library")


def test_every_term_written_by_the_code_exists() -> None:
    known = declared("library") | declared("schema")
    written = pyoxigraph.Store()
    triples = home_model.to_triples(profiles.load("ev").home)
    for name in profiles.names():
        triples += configuration.to_triples(profiles.load(name).configuration)
    triples += configuration.to_triples(full_configuration())
    written.extend(pyoxigraph.Quad(t.subject, t.predicate, t.object) for t in triples)

    assert used(written) - known == set()


@pytest.mark.parametrize("path", sorted(SOURCES.rglob("*.py")), ids=lambda p: p.name)
def test_every_term_read_by_the_code_exists(path: Path) -> None:
    read = set(re.findall(r"\beo:([A-Za-z][A-Za-z0-9_]*)", path.read_text(encoding="utf-8")))

    assert read - (declared("library") | declared("schema")) == set()


def test_both_graphs_are_loaded(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    home_model.load_vocabulary(graph)

    assert set(graph.named_graphs(BASE)) == {GRAPH_LIBRARY, GRAPH_SCHEMA}


ROOT = Path(__file__).parents[3]
V1_NAMESPACES = ("http://ontology.local/maison#", "http://webprotege.stanford.edu/")
# Ontologie de la v1 : seulement dans le dépôt d'origine, non publié.
V1_ONTOLOGY = ROOT / "ontology" / "ontology.ttl"


def v1_individuals() -> set[str]:
    """Noms des individus de la v1 (la maison de référence), à ne jamais reprendre."""
    found = pyoxigraph.Store()
    found.load(V1_ONTOLOGY.read_bytes(), format=pyoxigraph.RdfFormat.TURTLE)
    individual = pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#NamedIndividual")
    label = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    names = set()
    for quad in found.quads_for_pattern(None, None, individual):
        subject = quad.subject
        if isinstance(subject, pyoxigraph.NamedNode) and subject.value.startswith(V1_NAMESPACES):
            names.add(subject.value.rsplit("#", 1)[-1].rsplit("/", 1)[-1])
            names |= {
                q.object.value
                for q in found.quads_for_pattern(subject, label, None)
                if isinstance(q.object, pyoxigraph.Literal)
            }
    return {n for n in names if "_" in n}  # noms composés : les mots seuls sont trop courants


@pytest.mark.skipif(not V1_ONTOLOGY.is_file(), reason="sans l'ontologie de la v1")
def test_nothing_of_the_v1_house_in_the_application() -> None:
    names = v1_individuals()
    assert len(names) > 20
    texts = [
        p
        for p in (ROOT / "app").rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".ts", ".tsx", ".json", ".ttl", ".md", ".csv"}
        and "node_modules" not in p.parts
        and p != Path(__file__).resolve()  # ce test cite les espaces de noms de la v1
    ]
    for path in texts:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not any(ns in text for ns in V1_NAMESPACES), path
        assert not [n for n in names if n in text], path
