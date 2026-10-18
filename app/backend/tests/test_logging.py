import logging

from wattslot.main import HealthCheckFilter


def _access_record(path: str) -> logging.LogRecord:
    # Forme des enregistrements de « uvicorn.access » : (client, méthode, chemin, version, statut).
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )


def test_health_checks_are_not_logged() -> None:
    assert not HealthCheckFilter().filter(_access_record("/api/health"))


def test_other_requests_are_logged() -> None:
    assert HealthCheckFilter().filter(_access_record("/api/energy/sources"))
