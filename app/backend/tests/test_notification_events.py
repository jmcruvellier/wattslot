"""Notifications du catalogue (lot 5.6, PR 2) : « lancez X maintenant », écart au plan, batterie
pleine avant midi, prévision de demain qui chute ; conditions, textes en français et en anglais,
une fois par clé et par jour, heures de silence ; contre un faux HA."""

import asyncio
import copy
import sqlite3
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tests.test_notifications import PHONE, FakeHA
from tests.test_views_day import actual_of, state_of
from tests.v1_oracle import state_named
from wattslot import notification_events as events
from wattslot.notifications import (
    NotificationSettings,
    QuietHours,
    Rule,
    dispatch,
    save,
    send_test,
)
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database
from wattslot.views.display import find_item

PARIS = ZoneInfo("Europe/Paris")
DROP_TEXT = (
    "Prévision de demain en baisse : 6,0 kWh de production, "
    "contre 10,0 kWh prévus plus tôt (-40 %)."
)
# Lave-linge prévu à 11 h, sèche-linge à 12 h 10, filtration à 13 h (durée, pas un cycle).
LINGE = state_named("tomorrow_laundry")
DAY = date(2025, 10, 15)


def _today() -> dict[str, Any]:
    return state_of(LINGE)


def _local(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2025, 10, day, hour, minute, tzinfo=PARIS)


def _without_cycles(state: dict[str, Any], hour: int = 14) -> dict[str, Any]:
    """Relevé à ``hour`` h 20 sans aucun cycle mesuré."""
    actual = actual_of(state, hour)
    actual["equipements_reels_horaire"] = {}
    return {**state, "donnees_reelles_cache": actual}


def _full_at(state: dict[str, Any], hour: int) -> dict[str, Any]:
    found = copy.deepcopy(state)
    battery = find_item(found["planning"], "Batterie")
    assert battery is not None
    capacity = found["capacite_batterie_kwh"]
    battery["soc_horaire_kwh"] = {h: capacity * (1.0 if h >= hour else 0.5) for h in range(24)}
    return found


# --- Conditions -------------------------------------------------------------------------------


def test_device_now_only_for_a_cycle_starting_within_the_hour() -> None:
    found = events.device_now(_today(), _local(10, 30), "fr")
    assert [c.message for c in found] == [
        "Lancez Lave-linge maintenant : son cycle est prévu à 11h00 ("
        + found[0].message.split("(")[1]
    ]
    assert found[0].key == "Lave-linge@660" and found[0].day == "2025-10-15"
    assert events.device_now(_today(), _local(9, 59), "fr") == []  # plus d'une heure avant
    # À midi : le sèche-linge (12 h 10), pas la filtration de 13 h, qui n'est pas un cycle.
    assert [c.key for c in events.device_now(_today(), _local(12, 0), "fr")] == ["Sèche-linge@730"]
    english = events.device_now(_today(), _local(10, 30), "en")[0].message
    assert english.startswith("Start the Lave-linge now: its cycle is planned at 11:00")


def test_device_now_skips_a_cycle_already_running() -> None:
    state = {**_today(), "donnees_reelles_cache": actual_of(_today(), 12)}  # lave-linge lancé
    assert [c.key for c in events.device_now(state, _local(10, 30), "fr")] == []


def test_plan_gap_for_a_cycle_not_started_after_30_minutes() -> None:
    late = _without_cycles(_today(), 11)  # relevé à 11 h 20 : lave-linge prévu à 11 h
    assert events.plan_gap(late, _local(11, 30), "fr") == []
    later = _without_cycles(_today(), 14)
    found = events.plan_gap(later, _local(14, 30), "fr")
    assert [c.key for c in found] == ["cycle:Lave-linge@660", "cycle:Sèche-linge@730"]
    assert found[0].message == "Lave-linge n'a pas démarré : son cycle était prévu à 11h00."
    assert events.plan_gap(_today(), _local(14, 30), "fr") == []  # sans relevé


def test_plan_gap_for_production_far_from_the_forecast() -> None:
    state = _without_cycles(_today(), 14)
    actual = state["donnees_reelles_cache"]
    actual["production_reelle_horaire"] = {
        h: v / 1.1 * 1.5 for h, v in actual["production_reelle_horaire"].items()
    }
    found = [c for c in events.plan_gap(state, _local(14, 30), "fr") if c.key == "production"]
    assert len(found) == 1
    assert found[0].message.startswith("Production solaire au-dessus de la prévision : ")
    # Prévu cumulé au prorata de l'heure en cours, comme les cartes au relevé (lot 5.1).
    assert "au relevé de 14h20" in found[0].message and "(+40 %)" in found[0].message
    # 10 % au-dessus : fiable, rien à signaler.
    assert not [
        c
        for c in events.plan_gap(_without_cycles(_today()), _local(14, 30), "fr")
        if c.key == "production"
    ]


def test_battery_full_before_noon_while_it_is_still_ahead() -> None:
    state = _full_at(_today(), 10)
    found = events.battery_full(state, _local(8), "fr")
    assert [c.message for c in found] == [
        "Batterie pleine prévue vers 11h00 : le surplus suivant partira sur le réseau, "
        "c'est le bon moment pour lancer un appareil."
    ]
    assert events.battery_full(state, _local(11), "fr") == []  # déjà passé
    assert events.battery_full(_full_at(_today(), 13), _local(8), "fr") == []  # après midi


def test_forecast_drop_against_the_highest_forecast_seen() -> None:
    state = {**_today(), "production_solaire_horaire": {12: 3.0, 13: 3.0}}
    assert events.forecast_drop(state, None, "fr") == []  # premier calcul : pas de référence
    assert events.forecast_drop(state, 8.0, "fr") == []  # -25 %
    found = events.forecast_drop(state, 10.0, "fr")
    assert [c.message for c in found] == [DROP_TEXT]
    assert found[0].day == "2025-10-15"


# --- Envoi après un calcul --------------------------------------------------------------------


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    return open_database(tmp_path)


def _save_plan(
    database: sqlite3.Connection, view: str, state: dict[str, Any], at: float = 1.0
) -> None:
    PlanStore(database).save(view, DAY, state, at, False)


def _run(client: FakeHA, database: sqlite3.Connection, local: datetime) -> list[Any]:
    errors: list[str] = []
    sent = asyncio.run(dispatch(client, database, local.astimezone(UTC), PARIS, errors))  # type: ignore[arg-type]
    assert errors == []
    return sent


def _enable(database: sqlite3.Connection, language: str = "fr", **rules: Rule) -> None:
    save(database, NotificationSettings(service=PHONE, language=language, **rules))  # type: ignore[arg-type]


def test_each_notification_is_sent_once_per_key_and_day(database: sqlite3.Connection) -> None:
    _save_plan(database, "today", _today())
    _enable(database, device_now=Rule(enabled=True))
    client = FakeHA()
    _run(client, database, _local(10, 30))
    _run(client, database, _local(10, 45))
    assert len(client.sent) == 1
    assert client.sent[0]["service_data"]["title"] == "À lancer maintenant"
    _run(client, database, _local(12, 0))  # le sèche-linge, une autre clé
    assert len(client.sent) == 2


def test_disabled_notifications_and_quiet_hours(database: sqlite3.Connection) -> None:
    _save_plan(database, "today", _full_at(_today(), 10))
    client = FakeHA()
    _enable(database)  # rien d'activé
    _run(client, database, _local(8))
    assert client.sent == []
    _enable(
        database,
        battery_full=Rule(enabled=True, quiet_hours=QuietHours(start=time(22), end=time(8, 30))),
    )
    _run(client, database, _local(8))
    assert client.sent == []  # silence : sautée
    _run(client, database, _local(9))
    assert [c["service_data"]["title"] for c in client.sent] == ["Batterie pleine avant midi"]


def test_english_and_own_device(database: sqlite3.Connection) -> None:
    _save_plan(database, "today", _without_cycles(_today()))
    tablet = "notify.mobile_app_tablet"
    _enable(database, language="en", plan_gap=Rule(enabled=True, service=tablet))
    client = FakeHA()
    sent = _run(client, database, _local(14, 30))
    assert client.services() == [tablet, tablet]
    assert client.sent[0]["service_data"]["title"] == "Off plan"
    assert sent[0].message == "The Lave-linge has not started: its cycle was planned at 11:00."


def test_forecast_drop_compares_calculations(database: sqlite3.Connection) -> None:
    tomorrow = {**_today(), "production_solaire_horaire": {12: 5.0, 13: 5.0}}
    _save_plan(database, "tomorrow", tomorrow)
    _enable(database, forecast_drop=Rule(enabled=True))
    client = FakeHA()
    _run(client, database, _local(8))  # référence : 10 kWh
    _save_plan(
        database, "tomorrow", {**tomorrow, "production_solaire_horaire": {12: 4.5, 13: 4.5}}, 2.0
    )
    _run(client, database, _local(9))  # -10 % : rien
    _save_plan(
        database, "tomorrow", {**tomorrow, "production_solaire_horaire": {12: 3.0, 13: 3.0}}, 3.0
    )
    _run(client, database, _local(10))  # -40 % par rapport à la plus haute (10 kWh)
    _run(client, database, _local(11))  # déjà envoyée pour ce jour
    assert [c["service_data"]["message"] for c in client.sent] == [DROP_TEXT]


def test_a_failing_notification_does_not_stop_the_others(database: sqlite3.Connection) -> None:
    _save_plan(database, "today", _full_at(_today(), 10))
    _enable(database, device_now=Rule(enabled=True), battery_full=Rule(enabled=True))

    class Flaky(FakeHA):
        async def command(self, command: str, **params: Any) -> None:
            if params["service_data"]["title"] == "À lancer maintenant":
                raise RuntimeError("service inconnu")
            await super().command(command, **params)

    client = Flaky()
    errors: list[str] = []
    asyncio.run(dispatch(client, database, _local(10, 30).astimezone(UTC), PARIS, errors))  # type: ignore[arg-type]
    assert errors == ["notification device_now : RuntimeError: service inconnu"]
    assert [c["service_data"]["title"] for c in client.sent] == ["Batterie pleine avant midi"]


def test_test_send_uses_the_current_situation_or_an_example(database: sqlite3.Connection) -> None:
    _enable(database)
    client = FakeHA()
    # Sans plan : un exemple, marqué comme essai.
    sent = asyncio.run(send_test(client, database, "battery_full", _local(9), PARIS))  # type: ignore[arg-type]
    assert sent.message.startswith("[Essai] Batterie pleine prévue vers 9h00")
    _save_plan(database, "today", _today())
    sent = asyncio.run(send_test(client, database, "device_now", _local(10, 30), PARIS))  # type: ignore[arg-type]
    assert sent.message.startswith("[Essai] Lancez Lave-linge maintenant")
    assert client.sent[-1]["service_data"]["title"] == "À lancer maintenant"
