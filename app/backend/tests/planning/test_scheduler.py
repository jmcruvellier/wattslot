"""Planificateur : chaque heure à la minute choisie, la bascule de minuit, l'état des calculs."""

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from wattslot.planning.runner import RunReport
from wattslot.planning.scheduler import (
    PlanningScheduler,
    near_hourly,
    next_actual,
    next_hourly,
    next_wake,
)
from wattslot.planning.sources import ForecastUnavailable

PARIS = ZoneInfo("Europe/Paris")


def paris(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=PARIS)


def test_next_hourly_is_strictly_after_now() -> None:
    assert next_hourly(paris(2026, 10, 16, 10, 20), 59, PARIS) == paris(2026, 10, 16, 10, 59)
    assert next_hourly(paris(2026, 10, 16, 10, 59), 59, PARIS) == paris(2026, 10, 16, 11, 59)
    assert next_hourly(paris(2026, 10, 16, 23, 59, 30), 59, PARIS) == paris(2026, 10, 17, 0, 59)
    assert next_hourly(paris(2026, 10, 16, 10, 20), 0, PARIS) == paris(2026, 10, 16, 11, 0)


def test_next_hourly_across_daylight_saving_changes() -> None:
    # Passage à l'heure d'hiver (25/10/2026, 3 h → 2 h) : les deux 2 h 59 sont des échéances.
    first = next_hourly(paris(2026, 10, 25, 2, 30), 59, PARIS)
    second = next_hourly(first, 59, PARIS)
    assert (second - first).total_seconds() == 3600
    assert next_hourly(second, 59, PARIS).astimezone(PARIS).hour == 3
    # Passage à l'heure d'été (29/03/2026, 2 h → 3 h) : 1 h 59 puis 3 h 59.
    early = next_hourly(paris(2026, 3, 29, 1, 30), 59, PARIS)
    assert (next_hourly(early, 59, PARIS) - early).total_seconds() == 3600


def test_next_wake_prefers_the_midnight_rollover() -> None:
    wake, rollover = next_wake(paris(2026, 10, 16, 23, 59, 30), 59, PARIS)
    assert rollover and wake.astimezone(PARIS) == paris(2026, 10, 17, 0, 1)
    wake, rollover = next_wake(paris(2026, 10, 16, 10, 20), 59, PARIS)
    assert not rollover and wake == paris(2026, 10, 16, 10, 59)


def report(day: date, errors: list[str] | None = None) -> RunReport:
    return RunReport(
        day=day,
        started_at=datetime(2026, 10, 16, 8, tzinfo=UTC),
        manual=False,
        seconds_today=6.0,
        errors=errors or [],
    )


class Fake:
    def __init__(self) -> None:
        self.calls: list[datetime] = []
        self.plan_day: date | None = None
        self.fail = False
        self.no_forecast = False
        self.errors: list[str] = []
        self.refreshed: list[datetime] = []
        self.refresh_fails = False

    async def run(self, now: datetime) -> RunReport:
        self.calls.append(now)
        if self.fail:
            raise RuntimeError("Home Assistant non connecté")
        if self.no_forecast:
            raise ForecastUnavailable("2026-10-16")
        self.plan_day = now.astimezone(PARIS).date()
        return report(self.plan_day, self.errors)

    async def refresh(self, now: datetime) -> None:
        if self.refresh_fails:
            raise RuntimeError("brut illisible")
        self.refreshed.append(now)

    def scheduler(self, lock: asyncio.Lock | None = None) -> PlanningScheduler:
        return PlanningScheduler(
            self.run,
            lambda: (True, 59, 15),
            lambda: PARIS,
            lambda: self.plan_day,
            lock or asyncio.Lock(),
            self.refresh,
        )


def test_tick_records_the_report_and_errors() -> None:
    fake = Fake()
    scheduler = fake.scheduler()
    now = paris(2026, 10, 16, 9, 59).astimezone(UTC)

    asyncio.run(scheduler.tick(now))
    status = scheduler.status()
    assert status.last_success_at == now and status.last_error is None
    assert status.last_report is not None and status.last_report.seconds_today == 6.0

    fake.errors = ["horizon : ValueError"]
    asyncio.run(scheduler.tick(now))
    assert scheduler.status().last_error == "horizon : ValueError"

    fake.fail = True
    later = paris(2026, 10, 16, 10, 59).astimezone(UTC)
    asyncio.run(scheduler.tick(later))
    status = scheduler.status()
    assert status.last_run_at == later and status.last_success_at == now
    assert status.last_error == "RuntimeError: Home Assistant non connecté"
    assert status.last_error_code == "internal"
    assert status.last_report is not None  # le dernier bilan réussi reste lisible

    # Sans prévision : signalé à part par le diagnostic (« no_forecast »), pas en erreur interne.
    fake.fail, fake.no_forecast = False, True
    asyncio.run(scheduler.tick(later))
    assert scheduler.status().last_error_code == "no_forecast"


def test_rollover_runs_only_when_the_day_is_not_computed_yet() -> None:
    fake = Fake()
    scheduler = fake.scheduler()
    fake.plan_day = date(2026, 10, 16)
    midnight = paris(2026, 10, 17, 0, 1).astimezone(UTC)

    asyncio.run(scheduler.tick(midnight, is_rollover=True))
    assert len(fake.calls) == 1 and fake.plan_day == date(2026, 10, 17)

    asyncio.run(scheduler.tick(midnight, is_rollover=True))
    assert len(fake.calls) == 1


def test_start_and_stop_report_the_next_run() -> None:
    fake = Fake()

    async def scenario() -> None:
        scheduler = fake.scheduler()
        scheduler.start()
        await asyncio.sleep(0)
        status = scheduler.status()
        assert status.running and status.enabled and status.next_run_at is not None
        await scheduler.stop()
        assert not scheduler.status().running

    asyncio.run(scenario())
    assert fake.calls == []


def test_status_route_and_diagnostic_without_home_assistant(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from tests.test_health import _settings
    from wattslot.main import create_app

    with TestClient(create_app(_settings(tmp_path))) as api:
        status = api.get("/api/planning/status").json()
        assert status["running"] is False and status["enabled"] is False
        assert api.get("/api/diagnostic").json()["planning"] is None


def test_next_actual_every_quarter_hour() -> None:
    assert next_actual(paris(2026, 10, 18, 10, 47), 15, PARIS) == paris(2026, 10, 18, 11, 0)
    assert next_actual(paris(2026, 10, 18, 10, 15), 15, PARIS) == paris(2026, 10, 18, 10, 30)
    assert next_actual(paris(2026, 10, 18, 10, 14, 59), 15, PARIS) == paris(2026, 10, 18, 10, 15)
    assert next_actual(paris(2026, 10, 18, 23, 50), 15, PARIS) == paris(2026, 10, 19, 0, 0)
    assert next_actual(paris(2026, 10, 18, 10, 47), 60, PARIS) == paris(2026, 10, 18, 11, 0)
    # Passage à l'heure d'hiver : les deux 2 h 45 sont des échéances, à une heure d'écart.
    first = next_actual(paris(2026, 10, 25, 2, 40), 15, PARIS)
    second = next_actual(
        next_actual(next_actual(next_actual(first, 15, PARIS), 15, PARIS), 15, PARIS), 15, PARIS
    )
    assert (second - first).total_seconds() == 3600


def test_near_hourly_on_both_sides_of_the_run_minute() -> None:
    assert near_hourly(paris(2026, 10, 18, 10, 55), 59, PARIS)
    assert near_hourly(paris(2026, 10, 18, 11, 0), 59, PARIS)
    assert not near_hourly(paris(2026, 10, 18, 10, 45), 59, PARIS)
    assert not near_hourly(paris(2026, 10, 18, 11, 15), 59, PARIS)
    assert near_hourly(paris(2026, 10, 18, 10, 58), 0, PARIS)


def test_refresh_actual_rereads_today_between_two_runs() -> None:
    fake = Fake()
    scheduler = fake.scheduler()
    fake.plan_day = date(2026, 10, 18)
    for minute in (15, 30, 45):
        moment = paris(2026, 10, 18, 10, minute).astimezone(UTC)
        assert asyncio.run(scheduler.refresh_actual(moment, 59))
    assert len(fake.refreshed) == 3 and fake.calls == []
    status = scheduler.status()
    assert status.last_actual_at == paris(2026, 10, 18, 10, 45)
    assert status.last_actual_seconds is not None

    # Près du calcul horaire (h00 après celui de h59) : il relit lui-même le réel.
    assert not asyncio.run(scheduler.refresh_actual(paris(2026, 10, 18, 11, 0), 59))
    assert len(fake.refreshed) == 3

    # Un échec est noté et ne déplace pas la dernière relecture.
    fake.refresh_fails = True
    assert not asyncio.run(scheduler.refresh_actual(paris(2026, 10, 18, 11, 15), 59))
    assert scheduler.status().last_actual_at == paris(2026, 10, 18, 10, 45)


def test_refresh_actual_does_nothing_on_yesterday_s_plan() -> None:
    fake = Fake()
    scheduler = fake.scheduler()
    fake.plan_day = date(2026, 10, 17)
    assert not asyncio.run(scheduler.refresh_actual(paris(2026, 10, 18, 0, 15), 59))
    fake.plan_day = None
    assert not asyncio.run(scheduler.refresh_actual(paris(2026, 10, 18, 0, 30), 59))
    assert fake.refreshed == [] and fake.calls == []


def test_refresh_actual_skips_while_a_run_holds_the_lock() -> None:
    fake = Fake()
    fake.plan_day = date(2026, 10, 18)

    async def scenario() -> None:
        lock = asyncio.Lock()
        scheduler = fake.scheduler(lock)
        async with lock:  # calcul en cours (horaire ou bouton)
            assert not await scheduler.refresh_actual(paris(2026, 10, 18, 10, 30), 59)
        assert await scheduler.refresh_actual(paris(2026, 10, 18, 10, 30), 59)

    asyncio.run(scenario())
    assert len(fake.refreshed) == 1


def test_periodic_refresh_off_when_the_period_is_zero() -> None:
    fake = Fake()
    fake.plan_day = date(2026, 10, 18)

    async def scenario() -> None:
        scheduler = PlanningScheduler(
            fake.run,
            lambda: (True, 59, 0),
            lambda: PARIS,
            lambda: fake.plan_day,
            asyncio.Lock(),
            fake.refresh,
        )
        scheduler.start()
        await asyncio.sleep(0)
        assert scheduler.status().running
        await scheduler.stop()

    asyncio.run(scenario())
    assert fake.refreshed == []
