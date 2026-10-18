"""Langues des textes rédigés par le serveur (lot 5.7) : explications, recommandation,
avertissements du plan et notifications, dans les six langues de l'interface.

Le français et l'anglais sont relus ; l'allemand, le néerlandais, l'espagnol et l'italien sont
préparés puis « à relire » par des natifs (phase 7), comme les catalogues de l'interface.
"""

from typing import Literal

Language = Literal["fr", "en", "de", "nl", "es", "it"]
LANGUAGES: tuple[Language, ...] = ("fr", "en", "de", "nl", "es", "it")
TO_REVIEW: tuple[Language, ...] = ("de", "nl", "es", "it")
DEFAULT: Language = "fr"


def language_of(lang: str | None) -> Language:
    """Langue prise en charge (« en-US » → « en »), sinon le français, comme jusqu'ici."""
    code = (lang or "").strip().lower().replace("_", "-").split("-")[0]
    for language in LANGUAGES:
        if code == language:
            return language
    return DEFAULT


def number(value: float, lang: str, decimals: int, signed: bool = False) -> str:
    """Nombre à la façon de la langue : virgule décimale partout sauf en anglais."""
    text = f"{value:+.{decimals}f}" if signed else f"{value:.{decimals}f}"
    return text if lang == "en" else text.replace(".", ",")
