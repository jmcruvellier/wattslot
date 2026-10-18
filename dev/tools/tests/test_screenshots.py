"""Captures de la documentation (lot 7.2) : noms, préférences, horloge, adresses atteintes."""

from tools.demo_home import NOW
from tools.screenshots import (
    LANGUAGES,
    NOW_MS,
    OUTPUT,
    SHOTS,
    THEMES,
    local_url,
    output_path,
    storage,
)


def test_every_shot_has_a_distinct_file_per_language() -> None:
    paths = {output_path(language, shot) for language in LANGUAGES for shot in SHOTS}

    assert len(paths) == len(LANGUAGES) * len(SHOTS)
    assert output_path("fr", SHOTS[0]) == OUTPUT / "fr" / "today-phone-light.png"


def test_preferences_set_the_language_the_theme_and_open_curves() -> None:
    dark = next(shot for shot in SHOTS if shot.theme == "dark")

    prefs = storage("fr", dark)

    assert prefs["wattslot.language"] == "fr"
    assert prefs["wattslot.theme"] == THEMES["dark"] == "graphite"
    assert prefs["plan.curves"] == "open"


def test_the_browser_clock_is_the_demo_time() -> None:
    assert int(NOW.timestamp() * 1000) == NOW_MS


def test_only_local_addresses_are_reached() -> None:
    assert local_url("http://127.0.0.1:8199/api/health")
    assert local_url("http://localhost:8199/assets/index.js")
    assert local_url("data:image/png;base64,AAAA")
    assert not local_url("https://api.github.com/repos/x/y/releases/latest")
