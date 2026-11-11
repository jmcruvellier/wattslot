"""Plusieurs batteries : leur état de charge mesuré est un seul, pondéré par la capacité, comme
celui d'où part le calcul ; leurs compteurs sont additionnés. Défaut trouvé avec la maison de
test en triphasé : seule la première batterie était lue."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.planning.test_actual import DAY, MIDNIGHT, at, reading
from tests.planning.test_past import FakeReader
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.planning.actual import actual_day, combined
from wattslot.planning.runner import _soc_today
from wattslot.storage.raw import RawStores


def battery(key: str, capacity_kwh: float) -> HomeDevice:
    return HomeDevice(
        key=key,
        kind=DeviceKind.BATTERY,
        name=key,
        capacity_kwh=capacity_kwh,
        sensors=[
            HomeSensor(entity_id=f"sensor.{key}_soc", role=Role.STATE_OF_CHARGE),
            HomeSensor(entity_id=f"sensor.{key}_in", role=Role.ENERGY_CHARGED),
            HomeSensor(entity_id=f"sensor.{key}_out", role=Role.ENERGY_DISCHARGED),
        ],
    )


TWO = HomeModel(devices=[battery("small", 2.0), battery("large", 6.0)])


def test_readings_of_several_sensors_are_combined() -> None:
    small = [(at(2), 60.0), (at(0), 50.0)]
    large = [(at(1), 100.0)]

    assert combined([small]) == [(at(0), 50.0), (at(2), 60.0)]
    # Rien avant que les deux aient une valeur ; ensuite la moyenne pondérée par la capacité.
    assert combined([small, large], [2.0, 6.0]) == [(at(1), 87.5), (at(2), 90.0)]
    # Sans poids : la somme, pour des compteurs.
    assert combined([small, large]) == [(at(1), 150.0), (at(2), 160.0)]
    assert combined([]) == []


def test_the_measured_level_of_the_day_weighs_each_battery(tmp_path: Path) -> None:
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            reading("small", "sensor.small_soc", 40.0, at(-1)),
            reading("large", "sensor.large_soc", 80.0, at(-1)),
            reading("small", "sensor.small_soc", 20.0, at(9.5)),
            reading("large", "sensor.large_soc", 100.0, at(10.5)),
            reading("small", "sensor.small_in", 10.0, at(-1)),
            reading("large", "sensor.large_in", 30.0, at(-1)),
            reading("small", "sensor.small_in", 10.0, at(10)),
            reading("large", "sensor.large_in", 30.0, at(10)),
            reading("large", "sensor.large_in", 31.2, at(11)),
        ]
    )

    found: dict[str, Any] = actual_day(TWO, raw, DAY, at(12))

    # 2 kWh à 40 % et 6 kWh à 80 % : 70 % à minuit ; puis 65 % et 80 %.
    assert found["soc_pct_minuit"] == pytest.approx(70.0)
    assert found["soc_pct_fin_heure"][9] == pytest.approx(65.0)
    assert found["soc_pct_fin_heure"][11] == pytest.approx(80.0)
    assert found["soc_max_reel"]["pct"] == pytest.approx(80.0)
    # La charge de la grande batterie est vue, bien qu'elle ne soit pas la première.
    assert [(s["action"], s["energie_kwh"]) for s in found["batterie_reelle_segments"]] == [
        ("charge", 1.2)
    ]


def test_the_level_the_calculation_reads_weighs_each_battery() -> None:
    reader = FakeReader()
    eve = DAY - timedelta(days=1)
    reader.add("sensor.small_soc", eve, 23, last=40.0, max=45.0)
    reader.add("sensor.large_soc", eve, 23, last=80.0, max=80.0)
    reader.add("sensor.small_soc", DAY, 0, last=20.0, max=40.0)
    reader.add("sensor.large_soc", DAY, 0, last=100.0, max=100.0)
    reader.add("sensor.small_soc", DAY, 1, last=10.0, max=20.0)  # la grande n'a pas de relevé
    ctx = SimpleNamespace(raw=SimpleNamespace(zone=MIDNIGHT.tzinfo))

    by_hour, at_midnight, maximum = _soc_today(TWO, reader, at(2), ctx)  # type: ignore[arg-type]

    assert at_midnight == pytest.approx(70.0)
    assert by_hour == {0: pytest.approx(80.0)}  # une heure sans toutes les batteries : ignorée
    assert maximum == pytest.approx(85.0)
