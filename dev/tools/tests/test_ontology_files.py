"""Fichiers publiés de l'ontologie, en IRI absolues (lot 7.3)."""

import pyoxigraph

from tools.ontology_files import BASE, FILES, TARGET, render

OWL_ONTOLOGY = "http://www.w3.org/2002/07/owl#Ontology"


def test_the_published_files_follow_the_application() -> None:
    for name in FILES:
        assert (TARGET / name).read_text(encoding="utf-8") == render(name), (
            f"docs/ontology/{name} à régénérer : python dev/tools/ontology_files.py"
        )


def test_the_published_files_read_the_same_from_any_address() -> None:
    """Sans IRI relative : la base de lecture (adresse de la redirection) ne change rien."""
    for name in FILES:
        content = (TARGET / name).read_bytes()
        here, elsewhere = pyoxigraph.Store(), pyoxigraph.Store()
        here.load(content, format=pyoxigraph.RdfFormat.TURTLE, base_iri=BASE)
        elsewhere.load(
            content, format=pyoxigraph.RdfFormat.TURTLE, base_iri="https://example.org/x/y"
        )
        assert set(here) == set(elsewhere)


def test_each_ontology_is_declared_at_its_w3id_address() -> None:
    ontologies = {}
    for name in FILES:
        store = pyoxigraph.Store()
        store.load((TARGET / name).read_bytes(), format=pyoxigraph.RdfFormat.TURTLE)
        ontologies[name] = {
            q.subject.value
            for q in store.quads_for_pattern(None, None, None)
            if q.object == pyoxigraph.NamedNode(OWL_ONTOLOGY)
        }

    assert ontologies["home-energy.ttl"] == {f"{BASE}/library/home-energy"}
    assert ontologies["schema.ttl"] == {f"{BASE}/schema"}
    assert ontologies["ontology.ttl"] == ontologies["home-energy.ttl"] | ontologies["schema.ttl"]
