"""Forme normalisée de la bibliothèque et reprise d'un export de VocBench (lot 2b.3)."""

import pyoxigraph

from tools.library import BASE, LIBRARY, VOCAB, normalize, triples

SOSA = "http://www.w3.org/ns/sosa/"


def test_the_library_file_is_normalized_and_lossless() -> None:
    current = LIBRARY.read_bytes()

    assert LIBRARY.read_text(encoding="utf-8") == normalize(current)
    assert triples(normalize(current).encode("utf-8")) == triples(current)


def test_a_vocbench_export_comes_back_to_the_same_file() -> None:
    """Export de VocBench : IRI absolues, autre ordre, ontologies importées incluses."""
    store = pyoxigraph.Store()
    store.load(LIBRARY.read_bytes(), format=pyoxigraph.RdfFormat.TURTLE, base_iri=BASE)
    store.add(
        pyoxigraph.Quad(
            pyoxigraph.NamedNode(f"{SOSA}Sensor"),
            pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#label"),
            pyoxigraph.Literal("Sensor", language="en"),
        )
    )
    exported = store.dump(
        format=pyoxigraph.RdfFormat.N_TRIPLES, from_graph=pyoxigraph.DefaultGraph()
    )
    assert exported is not None and f"<{VOCAB}Home>".encode() in exported  # IRI absolues
    exported_turtle = b"\n".join(reversed(exported.splitlines()))

    assert normalize(exported_turtle) == LIBRARY.read_text(encoding="utf-8")


def test_a_change_shows_as_one_line() -> None:
    changed = LIBRARY.read_text(encoding="utf-8").replace('"Maison"@fr', '"Logement"@fr')

    before, after = normalize(LIBRARY.read_bytes()), normalize(changed.encode("utf-8"))

    diff = [a for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert len(diff) == 1 and "Logement" not in diff[0]
