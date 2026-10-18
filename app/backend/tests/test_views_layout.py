"""Disposition du dashboard (lot 5.5) : enregistrée dans l'installation, complétée, validée."""

from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot.main import create_app
from wattslot.views.layout import DAY_CARDS, WEEK_CARDS, complete_order, load_layout


def test_default_layout_lists_the_whole_catalog(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        found = api.get("/api/settings/dashboard").json()

    assert found["default"] is True
    assert found["today"] == {"order": list(DAY_CARDS), "hidden": []}
    assert found["week"]["order"] == list(WEEK_CARDS)
    assert found["indicators"] == {"highlight": None, "hidden": []}


def test_the_layout_is_kept_in_the_installation_and_reset(tmp_path: Path) -> None:
    layout = {
        "today": {"order": ["energy", "summary"], "hidden": ["grid"]},
        "week": {"order": ["days", "production", "consumption", "soc"], "hidden": ["consumption"]},
        "indicators": {"highlight": "co2_kg", "hidden": ["battery_throughput_kwh"]},
    }
    with TestClient(create_app(_settings(tmp_path))) as api:
        saved = api.put("/api/settings/dashboard", json=layout)
        assert saved.status_code == 200 and saved.json()["default"] is False

        # Un autre navigateur lit la même disposition, gardée en base.
        assert load_layout(api.app.state.database) is not None  # type: ignore[attr-defined]
        found = api.get("/api/settings/dashboard").json()
        assert found["today"]["order"] == [
            "energy",
            "indicators",
            "explanations",
            "summary",
            "timeline",
            "soc",
            "grid",
        ]
        assert found["today"]["hidden"] == ["grid"]
        assert found["yesterday"]["order"] == list(DAY_CARDS)  # chaque vue la sienne
        assert found["week"]["order"] == ["days", "production", "consumption", "soc"]
        assert found["indicators"]["highlight"] == "co2_kg"

        reset = api.delete("/api/settings/dashboard").json()
        assert reset["default"] is True and reset["today"]["hidden"] == []
        assert api.get("/api/settings/dashboard").json()["default"] is True


def test_unknown_or_duplicate_cards_are_refused(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        for layout in (
            {"today": {"order": ["meteo"]}},
            {"week": {"hidden": ["timeline"]}},
            {"today": {"order": ["soc", "soc"]}},
            {"indicators": {"highlight": "euros"}},
            {"indicators": {"highlight": "cost_eur", "hidden": ["cost_eur"]}},
        ):
            assert api.put("/api/settings/dashboard", json=layout).status_code == 422, layout
        assert api.get("/api/settings/dashboard").json()["default"] is True


def test_a_new_card_takes_its_default_place() -> None:
    # Disposition enregistrée avant l'ajout de « indicators » et « explanations » : chacune
    # suit la carte qui la précède dans l'ordre par défaut, où que celle-ci ait été déplacée.
    saved = ["summary", "timeline", "grid", "soc", "energy"]
    assert complete_order(saved, DAY_CARDS) == [*saved, "indicators", "explanations"]
    assert complete_order(["energy", "summary", "timeline", "soc", "grid"], DAY_CARDS)[:3] == [
        "energy",
        "indicators",
        "explanations",
    ]
    # Sans carte qui la précède : en tête.
    assert complete_order(["grid"], ("summary", "grid")) == ["summary", "grid"]
