"""Contrôle des données personnelles dans les fichiers publiés (lot 7.1 de la phase 7).

Parcourt les fichiers suivis par git que ``publish.txt`` retient pour le dépôt public, avec deux
familles de règles :

- **règles génériques** (ci-dessous) : adresses IPv4 privées (sauf le réseau interne du
  Supervisor de HA, connu de tous), jetons (JWT de HA, GitHub), adresses e-mail (sauf
  ``noreply`` et ``example``), adresses MAC ;
- **liste personnelle** : un terme par ligne (prénoms, noms d'hôtes, identifiants d'entités de la
  maison de référence…), qui ne doit pas être dans le dépôt. Lue dans la variable
  ``PRIVACY_TERMS`` (secret de la CI), sinon dans le fichier ``PRIVACY_TERMS_FILE``, sinon dans
  ``~/.config/wattslot/privacy-terms.txt``. Un terme est cherché sans tenir compte de la casse, et
  seulement entouré d'autre chose que des lettres (« lea » ne trouve pas « galeas »).

La sortie donne ``fichier:ligne`` et le numéro de la règle, **jamais le texte trouvé** : les
journaux de la CI d'un dépôt public sont publics. Une ligne légitime porte ``privacy: ok`` et sa
raison.

Depuis la racine du dépôt : ``python dev/tools/privacy_check.py``.
"""

import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "publish.txt"
DEFAULT_TERMS_FILE = Path.home() / ".config" / "wattslot" / "privacy-terms.txt"
ALLOW_MARKER = "privacy: ok"
# Fichiers générés, sans donnée écrite à la main : empreintes et numéros de version seulement.
SKIPPED = {"package-lock.json"}

RULES: dict[str, re.Pattern[str]] = {
    "ipv4-privee": re.compile(
        r"(?<![\d.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?![\d.])"
    ),
    "jeton-jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    "jeton-github": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "e-mail": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "adresse-mac": re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"),
}
# Réseau interne du Supervisor de HA (ingress, extensions) : public, identique partout.
ALLOWED_IPV4 = re.compile(r"^172\.30\.3[23]\.\d{1,3}$")
ALLOWED_EMAIL = re.compile(r"(?:noreply|no-reply)|@example\.(?:com|org|net)$", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


def published(files: Iterable[str], manifest: Iterable[str]) -> list[str]:
    """Fichiers retenus par le manifeste (un dossier se termine par « / »)."""
    entries = [line.strip() for line in manifest if line.strip() and not line.startswith("#")]
    return [
        name
        for name in files
        if any(
            name == entry or (entry.endswith("/") and name.startswith(entry)) for entry in entries
        )
    ]


def personal_terms(environ: dict[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    if env.get("PRIVACY_TERMS"):
        text = env["PRIVACY_TERMS"]
    else:
        path = (
            Path(env["PRIVACY_TERMS_FILE"]) if env.get("PRIVACY_TERMS_FILE") else DEFAULT_TERMS_FILE
        )
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return [
        term.strip()
        for term in text.splitlines()
        if term.strip() and not term.strip().startswith("#")
    ]


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![^\W\d_]){re.escape(term)}(?![^\W\d_])", re.IGNORECASE)


def scan(path: str, text: str, terms: list[str]) -> Iterator[Finding]:
    patterns = [_term_pattern(term) for term in terms]
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for rule, pattern in RULES.items():
            for match in pattern.finditer(line):
                value = match.group(0)
                if rule == "ipv4-privee" and ALLOWED_IPV4.match(value):
                    continue
                if rule == "e-mail" and ALLOWED_EMAIL.search(value):
                    continue
                yield Finding(path, number, rule)
                break
        for index, pattern in enumerate(patterns, start=1):
            if pattern.search(line):
                yield Finding(path, number, f"terme personnel n° {index}")


def main() -> int:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    files = published(tracked, MANIFEST.read_text(encoding="utf-8").splitlines())
    terms = personal_terms()
    if not terms:
        print("Liste personnelle absente : règles génériques seulement.")
    findings: list[Finding] = []
    for name in files:
        if Path(name).name in SKIPPED:
            continue
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # images, polices ; fichier supprimé mais encore suivi
        findings.extend(scan(name, text, terms))
    for finding in findings:
        print(finding)
    print(f"{len(files)} fichiers publiés contrôlés, {len(terms)} termes personnels : ", end="")
    print(f"{len(findings)} problème(s)." if findings else "aucun problème.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
