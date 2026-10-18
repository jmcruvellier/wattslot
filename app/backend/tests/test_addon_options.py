"""Options de l'extension lues dans ``/data/options.json`` (lot 6t.3)."""

import json
import logging
import re
from pathlib import Path

from fastapi.testclient import TestClient

from wattslot import addon_options
from wattslot.addon_options import AddonOptions
from wattslot.main import create_app
from wattslot.maintenance import Retention, load_retention, save_retention
from wattslot.runtime import RunMode, Settings
from wattslot.storage.database import open_database

ADDON = Path(__file__).parents[3] / "ha-addon" / "wattslot"
LOCAL = ("127.0.0.1", 50000)


def _settings(data_dir: Path, mode: RunMode) -> Settings:
    return Settings(mode=mode, data_dir=data_dir, static_dir=None, home_assistant=None)


def _write_options(data_dir: Path, **values: object) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / addon_options.OPTIONS_FILENAME).write_text(json.dumps(values), encoding="utf-8")


def test_defaults_without_options_file(tmp_path: Path) -> None:
    assert addon_options.load(tmp_path) == AddonOptions(
        log_level="info", raw_days=3, quarter_days=35
    )


def test_reads_the_options_file(tmp_path: Path) -> None:
    _write_options(tmp_path, log_level="debug", raw_days=5, quarter_days=60)

    assert addon_options.load(tmp_path) == AddonOptions(
        log_level="debug", raw_days=5, quarter_days=60
    )


def test_invalid_options_fall_back_to_defaults(tmp_path: Path) -> None:
    _write_options(tmp_path, raw_days=0)
    assert addon_options.load(tmp_path) == AddonOptions()

    (tmp_path / addon_options.OPTIONS_FILENAME).write_text("{", encoding="utf-8")
    assert addon_options.load(tmp_path) == AddonOptions()


def test_options_replace_raw_and_quarter_retention_but_keep_hours(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    save_retention(database, Retention(raw_days=10, quarter_days=100, hour_days=400))

    addon_options.apply_retention(database, AddonOptions(raw_days=4, quarter_days=40))

    assert load_retention(database) == Retention(raw_days=4, quarter_days=40, hour_days=400)


def test_addon_applies_options_at_startup(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_options(data_dir, log_level="warning", raw_days=7, quarter_days=90)

    with TestClient(create_app(_settings(data_dir, RunMode.ADDON)), client=LOCAL) as api:
        retention = api.get("/api/settings/retention").json()

    assert retention == {"raw_days": 7, "quarter_days": 90, "hour_days": None}
    assert logging.getLogger("wattslot").level == logging.WARNING
    create_app(_settings(data_dir, RunMode.STANDALONE))  # niveau par défaut rétabli


def test_standalone_ignores_the_options_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_options(data_dir, log_level="error", raw_days=7, quarter_days=90)

    with TestClient(create_app(_settings(data_dir, RunMode.STANDALONE))) as api:
        retention = api.get("/api/settings/retention").json()

    assert retention["raw_days"] == 3
    assert logging.getLogger("wattslot").level == logging.INFO


def test_addon_schema_matches_the_application_and_translations() -> None:
    """``options`` et ``schema`` de ``config.yaml`` et les traductions suivent ``AddonOptions``."""
    config = (ADDON / "config.yaml").read_text(encoding="utf-8")

    def block(text: str, name: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for line in text.split(f"\n{name}:\n", 1)[1].splitlines():
            if not line.startswith("  "):
                break
            key, _, value = line.strip().partition(":")
            found[key] = value.strip()
        return found

    options, schema = block(config, "options"), block(config, "schema")
    defaults = AddonOptions()
    assert options == {key: str(value) for key, value in defaults.model_dump().items()}
    fields = AddonOptions.model_fields
    assert schema == {
        "log_level": "list(debug|info|warning|error)",
        "raw_days": f"int({_bound(fields['raw_days'], 'ge')},{_bound(fields['raw_days'], 'le')})",
        "quarter_days": (
            f"int({_bound(fields['quarter_days'], 'ge')},{_bound(fields['quarter_days'], 'le')})"
        ),
    }
    for language in ("en", "fr"):
        translation = (ADDON / "translations" / f"{language}.yaml").read_text(encoding="utf-8")
        keys = re.findall(r"^  (\w+):$", translation, re.M)
        assert keys == list(fields), language


def _bound(field: object, name: str) -> int:
    for item in getattr(field, "metadata", []):
        if hasattr(item, name):
            return int(getattr(item, name))
    raise AssertionError(name)
