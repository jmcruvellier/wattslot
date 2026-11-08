"""Aperçu des prix d'un tarif en cours de saisie (grille de l'éditeur)."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot import templates
from wattslot.main import create_app
from wattslot.tariff import Holidays, PriceBand, Tariff, TariffContext, TariffKind, preview

MONDAY = date(2026, 11, 9)  # le mercredi 11 novembre est férié en France

WEEKEND = Tariff(
    kind=TariffKind.TIME_OF_USE,
    base_eur_kwh=0.25,
    bands=[PriceBand(start_hour=0, end_hour=24, eur_kwh=0.15, weekdays=[5, 6])],
    holidays=Holidays(country="FR"),
)


def test_seven_days_with_their_holidays() -> None:
    rows = preview(WEEKEND, MONDAY).rows
    assert [r.day.day for r in rows] == [9, 10, 11, 12, 13, 14, 15]
    assert [r.holiday for r in rows] == [False, False, True, False, False, False, False]
    assert [r.prices[12] for r in rows] == [0.25, 0.25, 0.15, 0.25, 0.25, 0.15, 0.15]
    assert all(len(r.prices) == 24 and r.color is None for r in rows)


def test_one_row_per_announced_day() -> None:
    ejp = templates.load("ejp").tariff
    rows = preview(ejp, MONDAY).rows
    assert [r.color for r in rows] == ["Normal", "EJP"]
    normal, peak = rows[0].prices, rows[1].prices
    assert set(normal) == {0.2}
    assert peak[0] == 0.9 and peak[1] == 0.2 and peak[7] == 0.9  # veille du même jour


def test_entity_prices_are_used() -> None:
    tariff = WEEKEND.model_copy(update={"base_eur_kwh_entity": "sensor.hp"})
    context = TariffContext(entity_prices={"sensor.hp": 0.3})
    assert preview(tariff, MONDAY, context).rows[0].prices[12] == 0.3


def test_preview_route(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        found = api.post("/api/configuration/tariff-preview", json=WEEKEND.model_dump(mode="json"))
    assert found.status_code == 200
    rows = found.json()["rows"]
    assert len(rows) == 7 and len(rows[0]["prices"]) == 24
