"""Devise de la maison (lot 7.3) : réglage, repli sur Home Assistant, montants écrits."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot import currency
from wattslot.main import create_app


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    currency.use_saved(None)
    currency.note_home_assistant(None)


def test_amounts_follow_the_language_and_the_currency() -> None:
    assert currency.amount(1.734, "fr") == "1,73\u00a0€"
    assert currency.amount(1.734, "en", "USD") == "$1.73"
    assert currency.amount(-0.2, "en", "GBP", signed=True) == "-£0.20"
    assert currency.amount(0.2, "de", "CHF", signed=True) == "+0,20\u00a0CHF"
    assert currency.amount(1234.5, "fr", "HUF") == "1234\u00a0Ft"  # sans décimales
    assert currency.amount(3.0, "it", "XYZ") == "3,00\u00a0XYZ"  # code inconnu : le code
    assert currency.per_kwh(0.138252, "en", "AUD") == "A$0.138/kWh"


def test_the_saved_currency_wins_over_home_assistant_then_the_euro() -> None:
    assert currency.active() == "EUR"
    currency.note_home_assistant("SEK")
    assert currency.active() == "SEK"
    currency.use_saved("NOK")
    assert currency.active() == "NOK"
    currency.note_home_assistant(None)
    currency.use_saved(None)
    assert currency.active() == "EUR"


def test_the_currency_api_saves_and_survives_a_restart(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/settings/currency").json()["effective"] == "EUR"
        saved = api.put("/api/settings/currency", json={"code": "CHF"}).json()
        assert (saved["code"], saved["effective"]) == ("CHF", "CHF")
        assert "JPY" in saved["choices"]
        assert api.put("/api/settings/currency", json={"code": "euro"}).status_code == 422
        database = api.app.state.database  # type: ignore[attr-defined]
        assert currency.load(database).code == "CHF"  # relu au démarrage suivant
        followed = api.put("/api/settings/currency", json={"code": None}).json()
        assert (followed["code"], followed["effective"]) == (None, "EUR")
        assert currency.load(database).code is None
