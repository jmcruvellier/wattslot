"""Textes rédigés par le serveur dans les six langues (lot 5.7) : catalogues complets (mêmes clés
et mêmes paramètres que l'anglais), avertissements identiques à la v1 en français et en anglais,
recommandation, vues et notifications dans chaque langue."""

import json
import re
import string
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.test_views_day import state_of
from tests.v1_oracle import STATES, v1
from wattslot import notification_events
from wattslot.languages import LANGUAGES, TO_REVIEW, language_of, number
from wattslot.main import create_app
from wattslot.notifications import NotificationSettings
from wattslot.planning.recommendation import recommendation, title
from wattslot.planning.store import PlanStore
from wattslot.planning.warning_texts import LOCALES as WARNING_LOCALES
from wattslot.planning.warning_texts import warning_text
from wattslot.storage.database import open_database
from wattslot.views.banners import as_stored

PLANNING_LOCALES = Path(__file__).parents[1] / "src/wattslot/planning/locales"


def _flat(value: dict[str, Any], prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    for key, item in value.items():
        path = f"{prefix}{key}"
        if isinstance(item, dict):
            found.update(_flat(item, f"{path}."))
        else:
            found[path] = str(item)
    return found


def _params(text: str) -> list[str]:
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def _same_as_english(catalogs: Mapping[str, Mapping[str, str]]) -> None:
    reference = catalogs["en"]
    for lang, current in catalogs.items():
        assert sorted(current) == sorted(reference), lang
        for key, text in reference.items():
            assert _params(current[key]) == _params(text), (lang, key)


def _json(folder: Path, lang: str) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((folder / f"{lang}.json").read_text(encoding="utf-8"))
    return found


def test_the_planning_catalogs_have_the_same_keys_and_parameters() -> None:
    _same_as_english({lang: _flat(_json(PLANNING_LOCALES, lang)) for lang in LANGUAGES})


def test_the_warning_catalogs_have_the_same_keys_and_parameters_and_a_status() -> None:
    catalogs: dict[str, dict[str, str]] = {
        lang: _flat(_json(WARNING_LOCALES, lang)) for lang in LANGUAGES
    }
    _same_as_english(catalogs)
    for lang, found in catalogs.items():
        assert found["_meta.status"] == ("to_review" if lang in TO_REVIEW else "reviewed")


def test_the_notification_texts_have_the_same_keys_and_parameters() -> None:
    assert set(notification_events.TEXTS) == set(LANGUAGES)
    _same_as_english(notification_events.TEXTS)


# Un avertissement de chaque code, avec des paramètres de chaque forme.
WARNINGS: list[dict[str, Any] | str] = [
    {"code": "profil_indisponible_du", "params": {"equipement": "Lave-linge", "status": "absent"}},
    {
        "code": "heures_insuffisantes_du",
        "params": {"equipement": "Lave-vaisselle", "duree_min": 140, "debut_min": 1290},
    },
    {"code": "profil_indisponible_attente", "params": {"equipement": "Sèche-linge", "status": "x"}},
    {
        "code": "dependance_non_placee",
        "params": {"equipement": "Sèche-linge", "depend_de": "Lave-linge"},
    },
    {
        "code": "heures_insuffisantes_attente",
        "params": {"equipement": "Lave-linge", "duree_min": 60, "debut_min": 1200},
    },
    {"code": "contrainte_impossible", "params": {"equipement": "Chauffe-eau", "contraintes": "c"}},
    {
        "code": "contrainte_non_respectee",
        "params": {"equipement": "Chauffe-eau", "contraintes": "c"},
    },
    {"code": "prevision_open_meteo", "params": {}},
    {"code": "prevision_horaire_indisponible", "params": {"jours": 7}},
    {"code": "panneau_sans_historique", "params": {"panneau": "Est", "jours": 3}},
    {"code": "soc_depart_approximatif", "params": {}},
    {"code": "regle_recurrence_non_geree", "params": {"equipement": "Piscine (filtration)"}},
    {"code": "horizon_interrompu", "params": {"jour": "2026-10-20", "raison": "pas de prévision"}},
    {
        "code": "tache_reportee",
        "params": {
            "equipement": "Sèche-linge",
            "jour": "2026-10-18",
            "pct_jour": 80,
            "pct_auj": 20,
        },
    },
    {
        "code": "tache_reportee_sans_creneau",
        "params": {"equipement": "Lave-linge", "jour": "2026-10-18"},
    },
    "Texte libre d'un ancien cache",
]


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_warnings_read_as_in_the_v1_in_french_and_english(lang: str) -> None:
    compared = 0
    for warning in WARNINGS:
        # Comparé à la v1 d'origine (résultats figés), pas à sa copie que le lot 5.8 supprime ;
        # les codes ajoutés par la v2 (contraintes, Open-Meteo…) n'y sont pas.
        expected = v1("i18n.texte_avertissement", warning, lang)
        if not expected.startswith("avertissement."):
            assert warning_text(warning, lang) == expected
            compared += 1
    assert compared >= 10


def test_warnings_in_the_new_languages() -> None:
    postponed = WARNINGS[13]
    assert warning_text(postponed, "de") == (
        "Trockner auf Sonntag, 18. Oktober 2026 verschoben: 80 % durch Solarstrom gedeckt, "
        "gegenüber 20 % heute."
    )
    assert warning_text(postponed, "es").startswith("Secadora aplazado al domingo, 18 de octubre")
    assert "21:30" in warning_text(WARNINGS[1], "it")  # 24 heures, à la minute
    assert "2 h 20 min" in warning_text(WARNINGS[1], "nl")
    for lang in LANGUAGES:
        for warning in WARNINGS:
            assert not re.search(r"\{\w+\}", warning_text(warning, lang)), (lang, warning)


def test_languages_and_numbers() -> None:
    assert language_of("de-DE") == "de" and language_of("xx") == "fr" and language_of(None) == "fr"
    assert number(1.5, "en", 2) == "1.50"
    assert [number(1.5, lang, 1) for lang in ("fr", "de", "nl", "es", "it")] == ["1,5"] * 5


def test_the_recommendation_in_every_language() -> None:
    state = as_stored(state_of(STATES[0]))
    texts = {lang: recommendation(state, lang) for lang in LANGUAGES}
    assert len(set(texts.values())) == len(LANGUAGES)
    assert len({title(lang) for lang in LANGUAGES}) == len(LANGUAGES)
    assert title("de") == "Energieplan des Tages"


def test_the_views_and_the_notifications_accept_every_language(tmp_path: Path) -> None:
    state = state_of(STATES[0])
    state["avertissements"] = [WARNINGS[13]]
    with TestClient(create_app(_settings(tmp_path))) as api:
        PlanStore(open_database(tmp_path / "data")).save(
            "today", date(2026, 10, 12), state, 1.0, False
        )
        notices = {
            lang: api.get(f"/api/views/today?lang={lang}").json()["notices"][0]["text"]
            for lang in LANGUAGES
        }
        settings = NotificationSettings(language="it").model_dump(mode="json")
        saved = api.put("/api/settings/notifications", json=settings)

    assert notices["de"].startswith("Trockner auf Sonntag")
    assert notices["nl"].startswith("Droger uitgesteld naar zondag")
    assert len(set(notices.values())) == len(LANGUAGES)
    assert saved.status_code == 200 and saved.json()["language"] == "it"
