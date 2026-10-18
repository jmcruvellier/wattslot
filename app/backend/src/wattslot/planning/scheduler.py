"""Planificateur interne (remplace n8n) : un calcul chaque heure, et la bascule de minuit.

- **Chaque heure**, à la minute choisie (59 par défaut, comme le déclencheur n8n de la v1) :
  calcul complet (``runner.run``) : le jour, demain, l'horizon.
- **Bascule de minuit** (0 h 01, ``rollover.py``) : si le plan du jour porte encore sur la
  veille, calcul du nouveau jour sans attendre l'heure suivante ; la veille est archivée.
- **Relecture des données réelles** (toutes les 15 min par défaut, ``actual_refresh_minutes``) :
  ``donnees_reelles_cache`` du plan du jour relu sur le brut, sans calcul, pour que l'écran ne
  reste pas jusqu'à une heure en retard. Rien près du calcul horaire (il relit lui-même le
  réel), ni pendant un calcul, ni si le plan du jour porte encore sur la veille.

Dans le fuseau de HA. Un calcul à la fois (verrou partagé avec ``POST /api/planning/run``) ;
sans HA connecté, le tour est sauté et noté. Un échec est noté et n'arrête pas la boucle.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from wattslot.planning.rollover import next_rollover, seconds_until
from wattslot.planning.runner import RunReport
from wattslot.planning.sources import ForecastUnavailable

logger = logging.getLogger(__name__)


class SchedulerStatus(BaseModel):
    running: bool
    enabled: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None  # dernier calcul terminé, réussi ou non
    last_success_at: datetime | None = None
    last_report: RunReport | None = None
    last_error: str | None = None
    # ``no_forecast`` : pas de prévision solaire (signalé à part par le diagnostic), sinon
    # ``internal`` ; aucun sans erreur.
    last_error_code: str | None = None
    last_actual_at: datetime | None = None  # dernière relecture des données réelles réussie
    last_actual_seconds: float | None = None  # sa durée


# Pas de relecture à moins de 5 min du calcul horaire : il relit lui-même le réel.
ACTUAL_GUARD_MINUTES = 5


def next_hourly(now: datetime, minute: int, zone: ZoneInfo) -> datetime:
    """Prochaine heure à la minute ``minute`` (heure locale), strictement après ``now``.

    En UTC : dans un même fuseau, Python compare et soustrait les heures murales, ce qui confond
    les deux 2 h 59 du passage à l'heure d'hiver.
    """
    local = now.astimezone(zone)
    target = local.replace(minute=minute, second=0, microsecond=0)
    if target <= local:
        target = (target.astimezone(UTC) + timedelta(hours=1)).astimezone(zone)
        target = target.replace(minute=minute)
    return target.astimezone(UTC)


def next_wake(now: datetime, minute: int, zone: ZoneInfo) -> tuple[datetime, bool]:
    """(prochain réveil, s'agit-il de la bascule de minuit)."""
    hourly, rollover = next_hourly(now, minute, zone), next_rollover(now, zone).astimezone(UTC)
    return (rollover, True) if rollover < hourly else (hourly, False)


def next_actual(now: datetime, period: int, zone: ZoneInfo) -> datetime:
    """Prochaine relecture : minute multiple de ``period`` dans l'heure, strictement après
    ``now`` (heure locale ; 15 → h00, h15, h30, h45)."""
    local = now.astimezone(zone)
    start = local.replace(minute=0, second=0, microsecond=0)
    minute = (local.minute // period + 1) * period
    if minute >= 60:
        return start.astimezone(UTC) + timedelta(hours=1)
    return start.replace(minute=minute).astimezone(UTC)


def near_hourly(now: datetime, minute: int, zone: ZoneInfo) -> bool:
    """``now`` à moins de ``ACTUAL_GUARD_MINUTES`` du calcul horaire, avant ou après."""
    gap = (now.astimezone(zone).minute - minute) % 60
    return min(gap, 60 - gap) < ACTUAL_GUARD_MINUTES


Runner = Callable[[datetime], Awaitable[RunReport]]
Refresher = Callable[[datetime], Awaitable[object]]
# (actif, minute du calcul horaire, période de relecture du réel en minutes, 0 sans relecture)
Settings = Callable[[], tuple[bool, int, int]]


class PlanningScheduler:
    def __init__(
        self,
        runner: Runner,
        settings: Settings,
        zone: Callable[[], ZoneInfo],
        today_plan_day: Callable[[], date | None],
        lock: asyncio.Lock,
        refresher: Refresher | None = None,
    ) -> None:
        self._runner = runner
        self._refresher = refresher
        self._settings = settings
        self._zone = zone
        self._today_plan_day = today_plan_day
        self._lock = lock
        self._task: asyncio.Task[None] | None = None
        self._actual_task: asyncio.Task[None] | None = None
        self._status = SchedulerStatus(running=False, enabled=True)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        if self._refresher is not None:
            self._actual_task = asyncio.create_task(self._actual_loop())

    async def stop(self) -> None:
        tasks = [t for t in (self._task, self._actual_task) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = self._actual_task = None

    def status(self) -> SchedulerStatus:
        enabled, _, _ = self._settings()
        return self._status.model_copy(
            update={"running": self._task is not None, "enabled": enabled}
        )

    async def _loop(self) -> None:
        while True:
            enabled, minute, _ = self._settings()
            wake, is_rollover = next_wake(datetime.now(UTC), minute, self._zone())
            self._status.next_run_at = wake
            # Boucle : un réveil en avance (horloge ajustée) ne doit pas sauter l'échéance.
            while (wait := seconds_until(wake, datetime.now(UTC))) > 0:
                await asyncio.sleep(wait)
            if enabled:
                await self.tick(datetime.now(UTC), is_rollover)

    async def _actual_loop(self) -> None:
        while True:
            _, _, period = self._settings()
            # Sans relecture (0), réveil au quart d'heure pour relire le réglage.
            wake = next_actual(datetime.now(UTC), period or 15, self._zone())
            while (wait := seconds_until(wake, datetime.now(UTC))) > 0:
                await asyncio.sleep(wait)
            enabled, minute, period = self._settings()
            if enabled and period:
                await self.refresh_actual(datetime.now(UTC), minute)

    async def refresh_actual(self, now: datetime, run_minute: int) -> bool:
        """Une relecture des données réelles du jour ; ``False`` si elle n'a pas lieu."""
        if self._refresher is None or near_hourly(now, run_minute, self._zone()):
            return False
        # Un calcul en cours relit lui-même le réel : pas d'attente derrière lui.
        if self._lock.locked():
            return False
        async with self._lock:
            # Plan de la veille : le calcul horaire (ou la bascule) fera le nouveau jour.
            if self._today_plan_day() != now.astimezone(self._zone()).date():
                return False
            started = time.monotonic()
            try:
                await self._refresher(now)
            except Exception:
                logger.exception("Relecture des données réelles impossible")
                return False
        self._status.last_actual_at = now
        self._status.last_actual_seconds = round(time.monotonic() - started, 2)
        return True

    async def tick(self, now: datetime, is_rollover: bool = False) -> RunReport | None:
        """Un tour : le calcul, ou rien à la bascule si le jour est déjà calculé."""
        today = now.astimezone(self._zone()).date()
        async with self._lock:
            if is_rollover and self._today_plan_day() == today:
                return None
            try:
                report = await self._runner(now)
            except ForecastUnavailable as exc:
                logger.warning(
                    "Calcul planifié impossible : aucune prévision solaire pour le %s", exc
                )
                self._status.last_run_at = now
                self._status.last_error = f"{type(exc).__name__}: {exc}"
                self._status.last_error_code = "no_forecast"
                return None
            except Exception as exc:
                logger.exception("Calcul planifié impossible")
                self._status.last_run_at = now
                self._status.last_error = f"{type(exc).__name__}: {exc}"
                self._status.last_error_code = "internal"
                return None
        self._status.last_run_at = now
        self._status.last_success_at = now
        self._status.last_report = report
        self._status.last_error = "; ".join(report.errors) or None
        self._status.last_error_code = "internal" if report.errors else None
        return report
