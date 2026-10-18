"""Captures d'écran de la documentation (lot 7.2).

Sur la démonstration de ``tools.demo`` (maison synthétique, aucune donnée réelle, heure figée à
14 h 30), pour chaque langue :

1. génère le dossier de données (31 jours simulés, calculs horaires du vrai serveur) ;
2. lance l'application sur ce dossier, heure figée, connectée au faux Home Assistant ;
3. photographie les écrans (``SHOTS``) sur téléphone et sur ordinateur, en thème clair (Ivoire)
   et sombre (Graphite), dans ``public/docs/images/<langue>/`` ; le navigateur est à la même
   heure que le serveur et n'atteint aucun site extérieur.

Prérequis : l'interface construite (``npm run build`` dans ``app/frontend``), l'environnement du
serveur (``pip install -e app/backend``, passé par ``--python``), et dans celui qui lance ce
script Playwright et Pillow (``pip install -r dev/requirements-screenshots.txt`` puis
``python -m playwright install chromium``). Depuis ``dev/`` :
``python -m tools.screenshots --python <python du serveur>``.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "dev"
OUTPUT = ROOT / "public" / "docs" / "images"
LANGUAGES = ("en", "fr")
THEMES = {"light": "ivory", "dark": "graphite"}
DEVICES = {"phone": (390, 844), "desktop": (1440, 900)}
NOW_MS = 1781094600000  # 10/06/2026 14:30 à Paris (``demo_home.NOW``), horloge du navigateur
TIME_ZONE = "Europe/Paris"


@dataclass(frozen=True)
class Shot:
    name: str  # nom du fichier, sans langue ni extension
    route: str  # adresse après « # »
    device: str  # clé de DEVICES
    theme: str  # clé de THEMES
    full_page: bool = False


SHOTS: tuple[Shot, ...] = (
    Shot("today-phone-light", "/today", "phone", "light"),
    Shot("today-phone-dark", "/today", "phone", "dark"),
    Shot("today-desktop-light", "/today", "desktop", "light"),
    Shot("planning-desktop-light", "/planning", "desktop", "light", full_page=True),
    Shot("planning-desktop-dark", "/planning", "desktop", "dark", full_page=True),
    Shot("planning-phone-light", "/planning", "phone", "light"),
    Shot("home-desktop-light", "/home", "desktop", "light"),
    Shot("assistant-desktop-light", "/assistant", "desktop", "light"),
    Shot("settings-desktop-light", "/settings", "desktop", "light"),
    Shot("status-desktop-light", "/settings/status", "desktop", "light"),
)


def output_path(language: str, shot: Shot) -> Path:
    return OUTPUT / language / f"{shot.name}.png"


def storage(language: str, shot: Shot) -> dict[str, str]:
    """Préférences du navigateur posées avant la capture (clés de l'interface)."""
    return {
        "wattslot.language": language,
        "wattslot.theme": THEMES[shot.theme],
        "wattslot.menu": "open",
        "plan.curves": "open",  # « Courbes détaillées » dépliées dans Planning
    }


def local_url(url: str) -> bool:
    """Adresse de l'application ou du poste ; le reste est bloqué pendant les captures (pas de
    vérification de mise à jour sur GitHub, par exemple)."""
    host = url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
    return url.startswith(("data:", "blob:")) or host in ("127.0.0.1", "localhost")


def server_python() -> str:
    """Python de l'environnement du serveur : celui de ``app/backend/.venv`` s'il existe."""
    for candidate in ("Scripts/python.exe", "bin/python"):
        path = ROOT / "app" / "backend" / ".venv" / candidate
        if path.is_file():
            return str(path)
    return sys.executable


def tool_env() -> dict[str, str]:
    """Le code de ce dépôt (``app/backend/src``) avant tout ``wattslot`` déjà installé."""
    env = dict(os.environ)
    paths = [str(ROOT / "app" / "backend" / "src"), str(DEV)]
    env["PYTHONPATH"] = os.pathsep.join(
        paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def wait_until_up(app_url: str, process: subprocess.Popen[bytes], timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(app_url + "/api/health", timeout=5) as response:
                health = json.loads(response.read())
            if health["connections"]["home_assistant"]["state"] == "connected":
                return
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            pass
        time.sleep(0.5)
    raise SystemExit("Le serveur de démonstration ne répond pas.")


@contextmanager
def demo_server(python: str, data: Path, port: int) -> Iterator[str]:
    command = [python, "-m", "tools.demo", "serve", "--data", str(data), "--port", str(port)]
    process = subprocess.Popen(command, cwd=DEV, env=tool_env())
    app_url = f"http://127.0.0.1:{port}"
    try:
        wait_until_up(app_url, process)
        yield app_url
    finally:
        process.terminate()
        process.wait(timeout=30)


def compress(path: Path) -> None:
    """Palette de 256 couleurs sans tramage : rendu identique pour une interface en aplats, PNG
    2 à 3 fois plus léger."""
    from PIL import Image

    with Image.open(path) as image:
        reduced = image.convert("RGB").quantize(
            colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
    reduced.save(path, "PNG", optimize=True)


def capture(app_url: str, language: str, shots: tuple[Shot, ...]) -> list[Path]:
    from playwright.sync_api import sync_playwright  # outil facultatif des développeurs

    written: list[Path] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for shot in shots:
            width, height = DEVICES[shot.device]
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2 if shot.device == "phone" else 1,
                is_mobile=shot.device == "phone",
                has_touch=shot.device == "phone",
                locale=language,
                timezone_id=TIME_ZONE,
            )
            context.route(
                "**/*",
                lambda route: route.continue_() if local_url(route.request.url) else route.abort(),
            )
            context.add_init_script(
                "for (const [k, v] of Object.entries("
                + json.dumps(storage(language, shot))
                + ")) localStorage.setItem(k, v);"
            )
            page = context.new_page()
            page.clock.set_fixed_time(NOW_MS)
            page.goto(f"{app_url}/?lang={language}#{shot.route}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)  # graphiques chargés à la demande, animations
            path = output_path(language, shot)
            path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path), full_page=shot.full_page)
            compress(path)
            written.append(path)
            context.close()
        browser.close()
    return written


def generate(python: str, language: str, data: Path) -> None:
    command = [python, "-m", "tools.demo", "generate", "--language", language, "--data", str(data)]
    subprocess.run(command, cwd=DEV, env=tool_env(), check=True, stdout=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", default=server_python(), help="python du serveur")
    parser.add_argument("--data", type=Path, default=Path(tempfile.gettempdir()) / "wattslot-demo")
    parser.add_argument("--port", type=int, default=8199)
    parser.add_argument("--language", choices=LANGUAGES, action="append")
    parser.add_argument("--only", action="append", help="nom d'une capture (plusieurs possibles)")
    parser.add_argument("--reuse", action="store_true", help="données déjà générées gardées")
    args = parser.parse_args()
    shots = tuple(s for s in SHOTS if not args.only or s.name in args.only)
    for language in args.language or LANGUAGES:
        data = args.data / language
        if not (args.reuse and (data / "demo.json").is_file()):
            print(f"Génération de la démonstration ({language})…", flush=True)
            generate(args.python, language, data)
        with demo_server(args.python, data, args.port) as app_url:
            for path in capture(app_url, language, shots):
                print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
