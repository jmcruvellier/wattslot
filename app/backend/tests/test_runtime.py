from pathlib import Path

import pytest

from wattslot.runtime import (
    SUPERVISOR_CORE_WEBSOCKET_URL,
    HomeAssistantTarget,
    RunMode,
    detect_run_mode,
    load_settings,
    websocket_url_from_http,
)


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, RunMode.STANDALONE),
        ({"SUPERVISOR_TOKEN": ""}, RunMode.STANDALONE),
        ({"SUPERVISOR_TOKEN": "abc"}, RunMode.ADDON),
    ],
)
def test_detect_run_mode(environ: dict[str, str], expected: RunMode) -> None:
    assert detect_run_mode(environ) == expected


def test_addon_uses_the_supervisor_proxy() -> None:
    settings = load_settings({"SUPERVISOR_TOKEN": "jeton"})

    assert settings.mode is RunMode.ADDON
    assert settings.home_assistant == HomeAssistantTarget(SUPERVISOR_CORE_WEBSOCKET_URL, "jeton")
    assert settings.data_dir == Path("/data")


def test_standalone_reads_url_and_token() -> None:
    settings = load_settings(
        {
            "HA_URL": "http://ha.local:8123/",
            "HA_TOKEN": "jeton",
            "WATTSLOT_DATA_DIR": "/tmp/wattslot",
        }
    )

    assert settings.mode is RunMode.STANDALONE
    assert settings.home_assistant == HomeAssistantTarget(
        "ws://ha.local:8123/api/websocket", "jeton"
    )
    assert settings.data_dir == Path("/tmp/wattslot")


def test_standalone_without_token_is_not_configured() -> None:
    assert load_settings({"HA_URL": "http://ha.local:8123"}).home_assistant is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://ha.local:8123", "ws://ha.local:8123/api/websocket"),
        ("https://ha.example.org", "wss://ha.example.org/api/websocket"),
        ("https://example.org/ha/", "wss://example.org/ha/api/websocket"),
    ],
)
def test_websocket_url_from_http(url: str, expected: str) -> None:
    assert websocket_url_from_http(url) == expected


@pytest.mark.parametrize("url", ["ha.local:8123", "ftp://ha.local", "http://"])
def test_websocket_url_rejects_invalid_addresses(url: str) -> None:
    with pytest.raises(ValueError):
        websocket_url_from_http(url)


def test_standalone_reads_the_token_from_a_file(tmp_path: Path) -> None:
    token_file = tmp_path / "ha_token"
    token_file.write_text("jeton-fichier\n", encoding="utf-8")

    settings = load_settings({"HA_URL": "http://ha:8123", "HA_TOKEN_FILE": str(token_file)})

    assert settings.home_assistant == HomeAssistantTarget(
        "ws://ha:8123/api/websocket", "jeton-fichier"
    )


def test_missing_token_file_is_not_configured(tmp_path: Path) -> None:
    settings = load_settings(
        {"HA_URL": "http://ha:8123", "HA_TOKEN_FILE": str(tmp_path / "absent")}
    )

    assert settings.home_assistant is None


def test_the_former_eo_variables_are_still_read(caplog: pytest.LogCaptureFixture) -> None:
    settings = load_settings({"EO_DATA_DIR": "/tmp/ancien", "EO_STATIC_DIR": "/tmp/static"})

    assert settings.data_dir == Path("/tmp/ancien")
    assert settings.static_dir == Path("/tmp/static")
    assert "EO_DATA_DIR est obsolète" in caplog.text


def test_the_wattslot_variables_win_over_the_former_ones() -> None:
    settings = load_settings({"WATTSLOT_DATA_DIR": "/tmp/nouveau", "EO_DATA_DIR": "/tmp/ancien"})

    assert settings.data_dir == Path("/tmp/nouveau")
