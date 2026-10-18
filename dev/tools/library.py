"""Bibliothèque « Énergie domestique » : forme normalisée, export de VocBench (lot 2b.3).

    python dev/tools/library.py                  # normalise le fichier de la bibliothèque
    python dev/tools/library.py export.ttl       # reprend un export Turtle de VocBench
    python dev/tools/library.py --check          # vérifie que le fichier est normalisé (CI)

La bibliothèque est maintenue dans l'atelier VocBench ; son fichier dans le dépôt
(``library/home-energy.ttl``) est toujours écrit sous une **forme normalisée**, la même quel que
soit l'outil qui l'a produite : IRI de l'application relatives (résolues au chargement avec
``BASE``), préfixes fixes, termes groupés par sorte et triés, propriétés dans un ordre fixe. Un
export de VocBench repris ainsi ne change donc le fichier que là où la bibliothèque a changé, et
l'aller-retour dépôt → VocBench → dépôt est sans changement.

Seuls les triplets de la bibliothèque sont gardés (sujets de l'espace de noms de l'application) :
les ontologies importées (SAREF, SOSA…) qu'un export inclurait sont écartées.
"""

import argparse
import re
import sys
from pathlib import Path

import pyoxigraph

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "app/backend/src/wattslot/ontology/library/home-energy.ttl"
SITE = "https://w3id.org/wattslot/"  # espace provisoire (ontology/__init__.py)
BASE = f"{SITE}ontology"
VOCAB = f"{BASE}#"

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
XSD = "http://www.w3.org/2001/XMLSchema#"
PREFIXES = {
    "owl": OWL,
    "rdfs": RDFS,
    "xsd": XSD,
    "sosa": "http://www.w3.org/ns/sosa/",
    "ssn": "http://www.w3.org/ns/ssn/",
    "saref": "https://saref.etsi.org/core/",
    "s4ener": "https://saref.etsi.org/saref4ener/",
}
LOCAL = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

# Sortes de termes, dans l'ordre du fichier ; un sujet prend la première qui s'applique.
KINDS = [
    (f"{OWL}Ontology", "Ontologie"),
    (f"{OWL}Class", "Classes"),
    (f"{OWL}ObjectProperty", "Propriétés d'objet"),
    (f"{OWL}DatatypeProperty", "Propriétés de données"),
    (f"{OWL}AnnotationProperty", "Propriétés d'annotation"),
]
PREDICATES = [
    f"{RDF}type",
    f"{RDFS}subClassOf",
    f"{RDFS}subPropertyOf",
    f"{RDFS}domain",
    f"{RDFS}range",
    f"{RDFS}label",
    f"{RDFS}comment",
]
LANGUAGES = ["fr", "en"]

HEADER = """\
# Bibliothèque « Énergie domestique » (phases 1 et 2 bis).
#
# Le domaine partagé par toutes les installations : maison, équipements, capteurs et leurs rôles,
# grandeurs, agrégats des relevés, alignés sur SAREF, SAREF4ENER, SOSA et SSN. Maintenue dans
# l'atelier VocBench ; ce fichier en est la forme normalisée (dev/tools/library.py), livrée avec
# l'application. Le schéma de l'application est à part, dans ../schema.ttl.
#
# Les IRI <#…> et <ontology/…> sont relatives : l'application les résout avec l'espace de noms
# déclaré dans wattslot/ontology/__init__.py (BASE).
"""


def triples(turtle: bytes) -> set[pyoxigraph.Triple]:
    """Triplets de la bibliothèque : sujets de l'espace de noms de l'application."""
    store = pyoxigraph.Store()
    store.load(turtle, format=pyoxigraph.RdfFormat.TURTLE, base_iri=BASE)
    return {
        pyoxigraph.Triple(q.subject, q.predicate, q.object)
        for q in store
        if isinstance(q.subject, pyoxigraph.NamedNode) and q.subject.value.startswith(SITE)
    }


def _iri(value: str) -> str:
    if value.startswith(VOCAB) and LOCAL.match(value[len(VOCAB) :]):
        return f"<#{value[len(VOCAB) :]}>"
    if value.startswith(SITE):
        return f"<{value[len(SITE) :]}>"
    if value == f"{RDF}type":
        return "a"
    for prefix, namespace in PREFIXES.items():
        local = value[len(namespace) :]
        if value.startswith(namespace) and (local == "" or LOCAL.match(local)):
            return f"{prefix}:{local}"
    return f"<{value}>"


def _literal(node: pyoxigraph.Literal) -> str:
    text = node.value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    if node.language:
        return f'"{text}"@{node.language}'
    if node.datatype.value == f"{XSD}string":
        return f'"{text}"'
    return f'"{text}"^^{_iri(node.datatype.value)}'


def _term(node: object) -> str:
    if isinstance(node, pyoxigraph.Literal):
        return _literal(node)
    if isinstance(node, pyoxigraph.NamedNode):
        return _iri(node.value)
    raise ValueError(f"nœud non géré dans la bibliothèque : {node!r}")


def _object_key(node: object) -> tuple[int, int, str]:
    if isinstance(node, pyoxigraph.Literal):
        lang = node.language or ""
        rank = LANGUAGES.index(lang) if lang in LANGUAGES else len(LANGUAGES)
        return (1, rank, node.value)
    return (0, 0, _term(node))


def _predicate_key(predicate: str) -> tuple[int, str]:
    rank = PREDICATES.index(predicate) if predicate in PREDICATES else len(PREDICATES)
    return (rank, _iri(predicate))


def normalize(turtle: bytes) -> str:
    found = triples(turtle)
    by_subject: dict[str, dict[str, list[object]]] = {}
    for triple in found:
        assert isinstance(triple.subject, pyoxigraph.NamedNode)
        by_subject.setdefault(triple.subject.value, {}).setdefault(
            triple.predicate.value, []
        ).append(triple.object)
    groups: dict[str, list[str]] = {title: [] for _, title in KINDS} | {"Individus": []}
    for subject, properties in by_subject.items():
        types = {t.value for t in properties.get(f"{RDF}type", []) if hasattr(t, "value")}
        title = next((t for kind, t in KINDS if kind in types), "Individus")
        groups[title].append(subject)
    lines = [HEADER]
    lines += [f"@prefix {prefix}: <{namespace}> ." for prefix, namespace in PREFIXES.items()]
    for title, subjects in groups.items():
        if not subjects:
            continue
        lines += ["", f"# --- {title} " + "-" * max(3, 92 - len(title)), ""]
        for subject in sorted(subjects, key=_iri):
            properties = by_subject[subject]
            parts = []
            for predicate in sorted(properties, key=_predicate_key):
                unique = {_term(o): o for o in properties[predicate]}.values()
                objects = sorted(unique, key=_object_key)
                parts.append(f"{_iri(predicate)} " + ", ".join(_term(o) for o in objects))
            lines.append(f"{_iri(subject)} " + " ;\n    ".join(parts) + " .")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", nargs="?", type=Path, help="export Turtle de VocBench")
    parser.add_argument("--check", action="store_true", help="vérifie sans écrire")
    args = parser.parse_args()
    current = LIBRARY.read_text(encoding="utf-8")
    if args.check:
        if current != normalize(current.encode("utf-8")):
            print("Bibliothèque à normaliser : python dev/tools/library.py")
            return 1
        return 0
    source = args.source.read_bytes() if args.source else current.encode("utf-8")
    before = triples(current.encode("utf-8"))
    after = triples(source)
    LIBRARY.write_text(normalize(source), encoding="utf-8", newline="\n")
    print(
        f"{LIBRARY.relative_to(ROOT)} : {len(after - before)} triplets ajoutés, "
        f"{len(before - after)} retirés"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
