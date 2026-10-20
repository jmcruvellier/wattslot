"""Qualité des données : limites physiques, anomalies, corrections rangées à part et appliquées
à la lecture des agrégats."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from wattslot import configuration, home_model
from wattslot.aggregation import HOUR, QUARTER, Aggregate, Aggregator
from wattslot.battery_settings import BatterySettings
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.corrections import CorrectionStore, Kind, Method, apply
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.ingestion import Ingestor, Target
from wattslot.quality import Sensor, correct, detect, router, scan, sensors
from wattslot.solar_panels import PanelArray, SolarPanels
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import RawStores, Reading
from wattslot.tariff import Tariff

LINKY = "sensor.grid_off_peak"
PLUG = "sensor.plug_energy"


def tariff(kva: float | None) -> Tariff:
    return Tariff(base_eur_kwh=0.2, contract_kva=kva)


HOME = HomeModel(
    devices=[
        HomeDevice(
            key="grid",
            kind=DeviceKind.GRID,
            name="Réseau",
            sensors=[HomeSensor(entity_id=LINKY, role=Role.ENERGY_IMPORTED)],
        ),
        HomeDevice(
            key="fridge",
            kind=DeviceKind.OTHER_LOAD,
            name="Frigo",
            sensors=[
                HomeSensor(entity_id=PLUG, role=Role.ENERGY_CONSUMED),
                HomeSensor(entity_id="sensor.plug_power", role=Role.POWER_CONSUMED),
            ],
        ),
        HomeDevice(
            key="solar",
            kind=DeviceKind.SOLAR,
            name="Panneaux",
            sensors=[HomeSensor(entity_id="sensor.solar_energy", role=Role.ENERGY_PRODUCED)],
        ),
        HomeDevice(
            key="battery",
            kind=DeviceKind.BATTERY,
            name="Batterie",
            capacity_kwh=5.0,
            sensors=[HomeSensor(entity_id="sensor.battery_in", role=Role.ENERGY_CHARGED)],
        ),
    ]
)

SAVED = Configuration(
    devices=[
        DeviceSettings(
            key="solar",
            behavior=Behavior.PRODUCTION,
            panels=SolarPanels(arrays=[PanelArray(kwp=2.0), PanelArray(kwp=1.0)]),
        )
    ],
    tariff=tariff(9),
    battery=BatterySettings(charge_max_w=2000),
)


# --- Limites physiques ------------------------------------------------------------------------


def test_physical_limits_come_from_the_contract_the_panels_and_the_battery() -> None:
    limits = {s.entity_id: round(s.limit_kwh_per_hour, 6) for s in sensors(HOME, SAVED)}

    assert limits == {
        LINKY: 10.8,  # 9 kVA, marge de 20 %
        PLUG: 10.8,  # aucun appareil ne tire plus que la maison
        "sensor.solar_energy": 3.6,  # 3 kWc
        "sensor.battery_in": 2.4,  # 2 000 W
    }  # la puissance n'est pas un compteur : pas de limite


def test_without_a_contract_the_largest_residential_one_is_assumed() -> None:
    found = sensors(HOME, Configuration(tariff=tariff(None)))

    assert next(s for s in found if s.entity_id == LINKY).limit_kwh_per_hour == 36 * 1.2


# --- Détection -------------------------------------------------------------------------------

T0 = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
GRID = Sensor(LINKY, "grid", Role.ENERGY_IMPORTED, 10.8)


def hourly(*values: float | None, entity_id: str = LINKY) -> list[Aggregate]:
    return [
        Aggregate(
            entity_id=entity_id,
            period=HOUR,
            start=T0 + timedelta(hours=n),
            energy_kwh=value,
        )
        for n, value in enumerate(values)
        if value is not None
    ]


def test_detects_a_spike_a_negative_value_and_a_gap() -> None:
    found = detect(GRID, HOUR, hourly(0.4, 23147.73, 0.3, -0.2, None, None, 0.5))

    assert [(a.kind, a.start, a.energy_kwh, a.missing) for a in found] == [
        (Kind.SPIKE, T0 + timedelta(hours=1), 23147.73, 0),
        (Kind.NEGATIVE, T0 + timedelta(hours=3), -0.2, 0),
        (Kind.GAP, T0 + timedelta(hours=4), None, 2),
    ]
    assert found[0].limit_kwh == 10.8
    assert found[0].device == "grid"


def test_quarter_limits_are_a_quarter_of_the_hour() -> None:
    quarters = [
        Aggregate(entity_id=LINKY, period=QUARTER, start=T0, energy_kwh=2.6),
        Aggregate(
            entity_id=LINKY, period=QUARTER, start=T0 + timedelta(minutes=15), energy_kwh=2.8
        ),
    ]

    assert [a.start for a in detect(GRID, QUARTER, quarters)] == [T0 + timedelta(minutes=15)]


# --- Corrections, avec un lecteur simulé -----------------------------------------------------


class FakeReader:
    """Agrégats d'origine en mémoire, corrigés à la lecture comme par ``Aggregator.read``."""

    def __init__(self, store: CorrectionStore, aggregates: list[Aggregate]) -> None:
        self._store = store
        self._aggregates = aggregates

    def read(
        self, entity_id: str, period: str, start: datetime, end: datetime, corrected: bool = True
    ) -> list[Aggregate]:
        found = [
            a
            for a in self._aggregates
            if a.entity_id == entity_id and a.period == period and start <= a.start < end
        ]
        if not corrected:
            return found
        return apply(found, self._store.active(entity_id, period, start, end))


def test_a_spike_is_discarded_once_automatically_and_can_be_undone(tmp_path: Path) -> None:
    store = CorrectionStore(open_database(tmp_path))
    reader = FakeReader(store, hourly(0.4, 23147.73, 0.3))
    window = {HOUR: (T0, T0 + timedelta(hours=3))}

    first = scan(reader, store, HOME, SAVED, window)

    assert first.corrected == 1
    correction = first.anomalies[0].correction
    assert correction is not None
    assert (correction.method, correction.automatic) == (Method.DISCARD, True)
    assert (correction.original_kwh, correction.corrected_kwh) == (23147.73, None)
    # Écartée : un trou dans les lectures, l'origine reste lisible.
    assert [a.energy_kwh for a in reader.read(LINKY, HOUR, T0, T0 + timedelta(hours=3))] == [
        0.4,
        0.3,
    ]
    assert len(reader.read(LINKY, HOUR, T0, T0 + timedelta(hours=3), corrected=False)) == 3
    assert scan(reader, store, HOME, SAVED, window).corrected == 0  # déjà corrigée

    assert store.undo(correction.id)
    again = scan(reader, store, HOME, SAVED, window)
    assert again.corrected == 0  # annulée par l'utilisateur : pas refaite
    assert again.anomalies[0].correction is None
    assert len(reader.read(LINKY, HOUR, T0, T0 + timedelta(hours=3))) == 3
    assert not store.undo(correction.id)


def test_scan_without_automatic_corrections_only_reports(tmp_path: Path) -> None:
    store = CorrectionStore(open_database(tmp_path))
    reader = FakeReader(store, hourly(0.4, 23147.73, 0.3))

    found = scan(reader, store, HOME, SAVED, {HOUR: (T0, T0 + timedelta(hours=3))}, automatic=False)

    assert found.corrected == 0
    assert store.list() == []


def test_an_estimate_is_the_mean_of_the_plausible_neighbours(tmp_path: Path) -> None:
    store = CorrectionStore(open_database(tmp_path))
    reader = FakeReader(store, hourly(0.2, 0.4, 23147.73, 0.6, 40000.0))
    spike = T0 + timedelta(hours=2)

    correction = correct(reader, store, HOME, SAVED, LINKY, HOUR, spike, Method.ESTIMATE)

    assert correction.corrected_kwh == 0.4  # (0,2 + 0,4 + 0,6) / 3 ; l'autre saut écarté
    assert (correction.kind, correction.automatic) == (Kind.SPIKE, False)
    hours = reader.read(LINKY, HOUR, T0, T0 + timedelta(hours=4))
    assert [a.energy_kwh for a in hours] == [0.2, 0.4, 0.4, 0.6]
    # Une nouvelle correction de la même période remplace la précédente.
    replaced = correct(reader, store, HOME, SAVED, LINKY, HOUR, spike, Method.DISCARD)
    assert [c.id for c in store.list()] == [replaced.id]
    assert len(store.list(undone=True)) == 2


def test_a_correction_needs_a_counter_a_value_and_neighbours(tmp_path: Path) -> None:
    store = CorrectionStore(open_database(tmp_path))
    reader = FakeReader(store, hourly(23147.73))

    for entity_id, start, method, code in [
        ("sensor.plug_power", T0, Method.DISCARD, "unknown_sensor"),
        (LINKY, T0 + timedelta(hours=5), Method.DISCARD, "no_value"),
        (LINKY, T0, Method.ESTIMATE, "no_neighbours"),
    ]:
        try:
            correct(reader, store, HOME, SAVED, entity_id, HOUR, start, method)
        except ValueError as error:
            assert str(error) == code
        else:
            raise AssertionError(code)


# --- Cas réel : compteur coupé un instant, compté comme une remise à zéro --------------------


class StubIngestor:
    backfilling = False
    targets: ClassVar[dict[str, Target]] = {
        LINKY: Target(LINKY, "urn:sensor:linky", Role.ENERGY_IMPORTED),
    }


def test_a_meter_dropping_to_zero_is_corrected_in_what_the_application_reads(
    tmp_path: Path,
) -> None:
    """Nuit du 19 au 20/10 : un compteur Linky envoie 0 un instant, puis son index ; la remise à
    zéro supposée ajoute tout l'index (23 147 kWh) à un quart d'heure et à son heure."""
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    iri = StubIngestor.targets[LINKY].sensor_iri
    readings = [
        Reading(LINKY, iri, 23147.0 + 0.01 * n, T0 + timedelta(minutes=5 * n)) for n in range(36)
    ]
    readings.append(Reading(LINKY, iri, 0.0, T0 + timedelta(hours=2, minutes=50, seconds=30)))
    raw.write(sorted(readings, key=lambda r: r.time))
    database = open_database(tmp_path)
    aggregator = Aggregator(cast(Ingestor, StubIngestor()), raw, graph, database)
    asyncio.run(aggregator.step(T0 + timedelta(hours=3, minutes=2)))
    store = CorrectionStore(database)
    end = T0 + timedelta(hours=3)

    before = [a.energy_kwh or 0 for a in aggregator.read(LINKY, HOUR, T0, end)]
    assert max(before) > 23000  # le saut, tel que l'agrégation le compte aujourd'hui

    found = scan(aggregator, store, HOME, SAVED, {HOUR: (T0, end), QUARTER: (T0, end)})

    assert {(a.kind, a.period) for a in found.anomalies} == {
        (Kind.SPIKE, HOUR),
        (Kind.SPIKE, QUARTER),
    }
    assert found.corrected == 2
    assert all((a.energy_kwh or 0) < 1 for a in aggregator.read(LINKY, HOUR, T0, end))
    assert all((a.energy_kwh or 0) < 1 for a in aggregator.read(LINKY, QUARTER, T0, end))
    assert max(a.energy_kwh or 0 for a in aggregator.read(LINKY, HOUR, T0, end, False)) > 23000


# --- Routes ----------------------------------------------------------------------------------


def test_routes_scan_correct_list_and_undo(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home_model.save(graph, HOME)
    configuration.save(graph, SAVED)
    database = open_database(tmp_path)
    store = CorrectionStore(database)
    app = FastAPI()
    app.include_router(router)
    app.state.graph = graph
    app.state.database = database
    app.state.aggregator = FakeReader(store, hourly(0.4, 23147.73, 0.3, 0.5))
    app.state.quality = None

    with TestClient(app) as api:
        scanned = api.post(
            "/api/quality/scan",
            json={"start": T0.isoformat(), "end": (T0 + timedelta(hours=4)).isoformat()},
        )
        assert scanned.status_code == 200
        assert scanned.json()["corrected"] == 1
        [anomaly] = scanned.json()["anomalies"]
        assert (anomaly["kind"], anomaly["device"]) == ("spike", "grid")

        estimated = api.post(
            "/api/quality/corrections",
            json={
                "entity_id": LINKY,
                "period": HOUR,
                "start": anomaly["start"],
                "method": "estimate",
            },
        )
        assert estimated.status_code == 201
        assert estimated.json()["corrected_kwh"] == 0.4

        listed = api.get("/api/quality/corrections").json()
        assert [c["method"] for c in listed] == ["estimate"]
        assert len(api.get("/api/quality/corrections?undone=true").json()) == 2

        assert api.delete(f"/api/quality/corrections/{listed[0]['id']}").status_code == 204
        assert api.delete(f"/api/quality/corrections/{listed[0]['id']}").status_code == 404
        refused = api.post(
            "/api/quality/corrections",
            json={
                "entity_id": "sensor.unknown",
                "period": HOUR,
                "start": T0.isoformat(),
                "method": "discard",
            },
        )
        assert (refused.status_code, refused.json()["detail"]) == (422, "unknown_sensor")
        naive = api.post(
            "/api/quality/scan", json={"start": "2026-10-19T00:00:00", "end": "2026-10-20T00:00:00"}
        )
        assert naive.status_code == 422
        assert api.get("/api/quality/status").json()["running"] is False
