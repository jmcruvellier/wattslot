"""Fichiers publiés de l'ontologie, servis par les adresses de w3id.org (lot 7.3).

    python dev/tools/ontology_files.py           # régénère docs/ontology/*.ttl
    python dev/tools/ontology_files.py --check   # vérifie qu'ils suivent l'application

La bibliothèque et le schéma livrés avec l'application écrivent leurs IRI en relatif (résolues
avec ``BASE`` au chargement). Lus depuis l'adresse vers laquelle w3id redirige, ils donneraient
des IRI fausses : ``docs/ontology/`` en garde une copie en IRI absolues, régénérée ici et
vérifiée par les tests de ``dev/``.

- ``home-energy.ttl`` : la bibliothèque (``…/ontology/library/home-energy``) ;
- ``schema.ttl`` : le schéma de l'application (``…/ontology/schema``) ;
- ``ontology.ttl`` : les deux réunis, pour un terme ``…/ontology#…`` (classes et propriétés des
  deux fichiers partagent cet espace de noms).
"""

import argparse
import sys
from pathlib import Path

import pyoxigraph

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "app/backend/src/wattslot/ontology"
TARGET = ROOT / "docs/ontology"
BASE = "https://w3id.org/wattslot/ontology"  # wattslot/ontology/__init__.py
PREFIXES = {
    "wattslot": f"{BASE}#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "sosa": "http://www.w3.org/ns/sosa/",
    "ssn": "http://www.w3.org/ns/ssn/",
    "saref": "https://saref.etsi.org/core/",
    "s4ener": "https://saref.etsi.org/saref4ener/",
}
LIBRARY = "library/home-energy.ttl"
SCHEMA = "schema.ttl"
FILES = {
    "home-energy.ttl": ([LIBRARY], f"{BASE}/library/home-energy"),
    "schema.ttl": ([SCHEMA], f"{BASE}/schema"),
    "ontology.ttl": ([LIBRARY, SCHEMA], f"{BASE}#"),
}
HEADER = """\
# WattSlot ontology: {iri}
#
# Generated from the application's files by dev/tools/ontology_files.py; do not edit.
# License: Apache-2.0, https://github.com/jmcruvellier/wattslot

"""


def _triples(sources: list[str]) -> list[pyoxigraph.Triple]:
    store = pyoxigraph.Store()
    for source in sources:
        store.load(
            (SOURCES / source).read_bytes(), format=pyoxigraph.RdfFormat.TURTLE, base_iri=BASE
        )
    return sorted((pyoxigraph.Triple(q.subject, q.predicate, q.object) for q in store), key=str)


def render(name: str) -> str:
    sources, iri = FILES[name]
    turtle = pyoxigraph.serialize(
        _triples(sources), format=pyoxigraph.RdfFormat.TURTLE, prefixes=PREFIXES
    )
    assert turtle is not None
    return HEADER.format(iri=iri) + turtle.decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="vérifie sans écrire")
    args = parser.parse_args()
    stale = []
    for name in FILES:
        path = TARGET / name
        content = render(name)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"{path.relative_to(ROOT)} écrit")
    if stale:
        print(f"À régénérer ({', '.join(stale)}) : python dev/tools/ontology_files.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
