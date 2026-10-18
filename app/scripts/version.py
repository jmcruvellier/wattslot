"""Version de l'application (lot 6t.1) : la même dans l'extension, le serveur et l'interface.

    python app/scripts/version.py              # affiche la version actuelle
    python app/scripts/version.py --check      # échoue si elle diffère d'un fichier à l'autre (CI)
    python app/scripts/version.py 0.8.0        # la change partout, et prépare le changelog

Fichiers mis à jour : `ha-addon/wattslot/config.yaml`, `app/backend/pyproject.toml`,
`app/frontend/package.json` et `package-lock.json`. Le changelog de l'extension
(`ha-addon/wattslot/CHANGELOG.md`, affiché par Home Assistant) reçoit en tête une section
avec les titres des PR fusionnées dans `main` depuis la version précédente (étiquette
`vX.Y.Z`, lue par `gh`), à relire et traduire en anglais avant la publication. Sans version
précédente, ou sans `gh`, la section reste à écrire à la main.

La publication elle-même se fait en poussant l'étiquette `vX.Y.Z` (workflow de publication).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "ha-addon/wattslot/config.yaml"
BACKEND = ROOT / "app/backend/pyproject.toml"
FRONTEND = ROOT / "app/frontend/package.json"
LOCK = ROOT / "app/frontend/package-lock.json"
CHANGELOG = ROOT / "ha-addon/wattslot/CHANGELOG.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
ADDON_LINE = re.compile(r'^version: "([^"]+)"$', re.M)
BACKEND_LINE = re.compile(r'^version = "([^"]+)"$', re.M)


def current() -> dict[str, str]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    return {
        "extension": ADDON_LINE.search(ADDON.read_text(encoding="utf-8")).group(1),  # type: ignore[union-attr]
        "serveur": BACKEND_LINE.search(BACKEND.read_text(encoding="utf-8")).group(1),  # type: ignore[union-attr]
        "interface": json.loads(FRONTEND.read_text(encoding="utf-8"))["version"],
        "verrou": lock["version"],
    }


def _replace(path: Path, pattern: re.Pattern[str], line: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(pattern.sub(line, text, count=1), encoding="utf-8", newline="\n")


def _set_json_version(path: Path, version: str, lock: bool) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    if lock:
        data["packages"][""]["version"] = version
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def previous_tag() -> str | None:
    """Dernière étiquette de version (vX.Y.Z), hors étiquettes de la v1 (v1.0)."""
    found = subprocess.run(
        ["git", "tag", "--list", "v*", "--sort=-version:refname"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split()
    return next((tag for tag in found if SEMVER.match(tag[1:])), None)


def merged_titles(since_tag: str) -> list[str] | None:
    """Titres des PR fusionnées dans `main` depuis l'étiquette ; None sans `gh`."""
    if shutil.which("gh") is None:
        return None
    date = subprocess.run(
        ["git", "log", "-1", "--format=%cI", since_tag],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    listed = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "merged",
            "--base",
            "main",
            "--limit",
            "500",
            "--search",
            f"merged:>{date}",
            "--json",
            "number,title",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [
        f"{pr['title']} (#{pr['number']})"
        for pr in sorted(json.loads(listed), key=lambda pr: pr["number"])
    ]


def add_changelog(version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    if f"\n## {version}\n" in text:
        return "section déjà présente"
    tag = previous_tag()
    titles = merged_titles(tag) if tag else None
    if titles:
        lines = "\n".join(f"- {title}" for title in titles)
        note = f"{len(titles)} PR depuis {tag}, à relire et traduire en anglais"
    else:
        lines = "- (to write)"
        note = "à écrire à la main (pas de version précédente ou pas de gh)"
    head, _, rest = text.partition("\n## ")
    section = f"\n## {version}\n\n{lines}\n"
    CHANGELOG.write_text(
        head + section + ("\n## " + rest if rest else ""), encoding="utf-8", newline="\n"
    )
    return note


def main(argv: list[str]) -> int:
    if len(argv) == 1 or argv[1] == "--check":
        found = current()
        for where, version in found.items():
            print(f"{where:10} {version}")
        if len(set(found.values())) > 1:
            print("Versions différentes : python app/scripts/version.py X.Y.Z", file=sys.stderr)
            return 1
        return 0
    version = argv[1].removeprefix("v")
    if not SEMVER.match(version):
        print(f"Version invalide : {argv[1]} (attendu X.Y.Z)", file=sys.stderr)
        return 2
    _replace(ADDON, ADDON_LINE, f'version: "{version}"')
    _replace(BACKEND, BACKEND_LINE, f'version = "{version}"')
    _set_json_version(FRONTEND, version, lock=False)
    _set_json_version(LOCK, version, lock=True)
    note = add_changelog(version)
    print(f"Version {version} écrite partout ; changelog : {note}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
