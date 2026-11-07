"""Accès en mode autonome : hôtes locaux seulement, pas d'écriture depuis un autre site."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot.local_access import local_host, parse_allowed, same_site
from wattslot.main import create_app
from wattslot.runtime import RunMode, load_settings


@pytest.mark.parametrize(
    "host",
    [
        "192.0.2.10:8100",
        "192.0.2.10",
        "[2001:db8::1]:8100",
        "localhost:8100",
        "nas:8100",
        "wattslot.local:8100",
        "wattslot.lan",
        "wattslot.home.arpa:8100",
        "WattSlot.Local.",
    ],
)
def test_local_hosts_are_admitted(host: str) -> None:
    assert local_host(host)


@pytest.mark.parametrize("host", ["attacker.example:8100", "rebind.example.com", "", ":8100"])
def test_public_names_are_refused(host: str) -> None:
    """Rebinding DNS : un nom public qui pointe vers l'adresse locale de WattSlot."""
    assert not local_host(host)


def test_allowed_hosts_add_names() -> None:
    allowed = parse_allowed(" wattslot.example.net , other.example.org:443")

    assert allowed == {"wattslot.example.net", "other.example.org"}
    assert local_host("wattslot.example.net:8100", allowed)
    assert not local_host("attacker.example", allowed)
    assert local_host("attacker.example", parse_allowed("*"))


def test_settings_from_the_environment() -> None:
    standalone = load_settings({"WATTSLOT_ALLOWED_HOSTS": "wattslot.example.net"})
    turned_on = load_settings({"WATTSLOT_HOME_ASSISTANT_CHAT": "true"})
    addon = load_settings({"SUPERVISOR_TOKEN": "test"})

    assert standalone.mode is RunMode.STANDALONE
    assert standalone.allowed_hosts == {"wattslot.example.net"}
    assert standalone.home_assistant_chat is False
    assert turned_on.home_assistant_chat is True
    assert addon.home_assistant_chat is True


def test_the_application_refuses_other_hosts_and_cross_site_writes(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path)), base_url="http://192.0.2.10:8100") as api:
        local = api.get("/api/health")
        rebound = api.get("/api/health", headers={"host": "rebind.example.com"})
        same_site = api.post(
            "/api/planning/run", headers={"origin": "http://192.0.2.10:8100"}
        ).status_code
        cross_site = api.post("/api/planning/run", headers={"origin": "https://attacker.example"})
        cross_site_read = api.get("/api/health", headers={"origin": "https://attacker.example"})

    assert local.status_code == 200
    assert rebound.status_code == 403
    assert same_site != 403
    assert cross_site.status_code == 403
    assert (
        cross_site_read.status_code == 200
    )  # lecture : la réponse reste illisible pour l'autre site


def test_the_addon_keeps_the_ingress_filter_only(tmp_path: Path) -> None:
    """En extension, l'ingress de HA protège déjà : le nom d'hôte n'est pas contrôlé."""
    settings = _settings(tmp_path, mode=RunMode.ADDON)
    with TestClient(create_app(settings), client=("172.30.32.2", 50000)) as api:
        response = api.get("/api/health", headers={"host": "anything.example"})

    assert response.status_code == 200


def test_writes_from_the_page_of_wattslot_only() -> None:
    proxied = parse_allowed("wattslot.example.net")

    assert same_site("http://192.0.2.10:8100", "192.0.2.10:8100")
    assert not same_site("https://attacker.example", "192.0.2.10:8100")
    assert not same_site("null", "192.0.2.10:8100")
    # Proxy inverse : Host réécrit vers l'adresse interne, Origin reste le nom public.
    assert same_site("https://wattslot.example.net", "127.0.0.1:8100", proxied)
