"""Télécharge les ontologies importées par la bibliothèque, pour l'atelier VocBench (lot 2b.3).

    python dev/tools/fetch_imports.py           # télécharge dans ontology/imports/

La bibliothèque « Énergie domestique » importe SAREF core, SAREF4ENER, SOSA et SSN
(``owl:imports``) sans les recopier. VocBench les charge comme **miroirs** en lecture seule, à
partir de ces fichiers. Versions épinglées, empreintes SHA-256 vérifiées : un fichier qui a
changé à la source est signalé au lieu d'être pris tel quel. Les fichiers ne sont pas versionnés
dans le dépôt (``ontology/imports/.gitignore``) : l'application n'en a pas besoin.
"""

import hashlib
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "ontology" / "imports"


@dataclass(frozen=True)
class Import:
    name: str  # fichier écrit dans ontology/imports/
    iri: str  # IRI importée par la bibliothèque (owl:imports)
    url: str  # version épinglée
    sha256: str


IMPORTS = [
    Import(
        "saref-core.ttl",
        "https://saref.etsi.org/core/",
        "https://saref.etsi.org/core/v4.1.1/saref.ttl",
        "28189acd8cfb49bf6b7e5709275a1162d943576f643b2cffdccfe20cc00ad701",
    ),
    Import(
        "saref4ener.ttl",
        "https://saref.etsi.org/saref4ener/",
        "https://saref.etsi.org/saref4ener/v2.1.1/saref4ener.ttl",
        "73fe1ccf93620d6125e1b178b10d481b33df3e01715838313de0268f761612da",
    ),
    # SOSA et SSN n'ont pas d'URL versionnée : l'empreinte dit si la W3C les a modifiés.
    Import(
        "sosa.ttl",
        "http://www.w3.org/ns/sosa/",
        "https://www.w3.org/ns/sosa/",
        "c70b0d1c843c0047e4c98e0a89392e46a05752ff6365bda7f7f55303905a0392",
    ),
    Import(
        "ssn.ttl",
        "http://www.w3.org/ns/ssn/",
        "https://www.w3.org/ns/ssn/",
        "184d86189191146e314cc52b1bceb96fca11e70aacbc160d71588102a5153eb9",
    ),
]

Fetch = Callable[[str], bytes]


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "text/turtle"})
    with urllib.request.urlopen(request, timeout=60) as response:  # URL épinglée ci-dessus
        body: bytes = response.read()
        return body


def fetch(fetch_url: Fetch = download, folder: Path = FOLDER) -> list[str]:
    """Écrit chaque import dont l'empreinte est la bonne ; renvoie les problèmes."""
    folder.mkdir(parents=True, exist_ok=True)
    problems = []
    for item in IMPORTS:
        body = fetch_url(item.url)
        digest = hashlib.sha256(body).hexdigest()
        if digest != item.sha256:
            problems.append(
                f"{item.name} : empreinte {digest}, attendue {item.sha256} ({item.url})"
            )
            continue
        (folder / item.name).write_bytes(body)
    return problems


def main() -> int:
    problems = fetch()
    for problem in problems:
        print(problem)
    if not problems:
        print(f"{len(IMPORTS)} ontologies dans {FOLDER.relative_to(ROOT)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
