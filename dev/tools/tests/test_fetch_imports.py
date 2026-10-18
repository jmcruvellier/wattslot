"""Miroirs des ontologies importées : versions épinglées, empreintes vérifiées (lot 2b.3)."""

import hashlib
from pathlib import Path

import pyoxigraph

from tools.fetch_imports import IMPORTS, fetch
from tools.library import LIBRARY, triples


def test_the_mirrors_are_the_imports_of_the_library() -> None:
    imports = {
        t.object.value
        for t in triples(LIBRARY.read_bytes())
        if t.predicate.value == "http://www.w3.org/2002/07/owl#imports"
        and isinstance(t.object, pyoxigraph.NamedNode)
    }

    assert imports == {item.iri for item in IMPORTS}


def test_only_files_with_the_pinned_digest_are_written(tmp_path: Path) -> None:
    good = {item.url: b"good" for item in IMPORTS}
    pinned = [item.sha256 for item in IMPORTS]
    assert all(len(d) == 64 for d in pinned)

    def fake(url: str) -> bytes:
        return good[url]

    problems = fetch(fake, tmp_path)

    assert len(problems) == len(IMPORTS)  # aucune empreinte ne correspond à « good »
    assert list(tmp_path.iterdir()) == []
    assert hashlib.sha256(b"good").hexdigest() in problems[0]
