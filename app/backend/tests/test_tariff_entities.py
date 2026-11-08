"""Prix fixes lus dans des entités de HA (hass-tarif-edf, issue #54), repli sur le prix saisi."""

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.planning.tariff_sources import needs_states, tariff_context
from wattslot.storage.graph import GraphStore
from wattslot.tariff import ColorPrices, PriceBand, Tariff, TariffContext, TariffKind

PARIS = ZoneInfo("Europe/Paris")
TODAY = date(2026, 11, 9)

OFF_PEAK = Tariff(
    kind=TariffKind.TIME_OF_USE,
    base_eur_kwh=0.27,
    base_eur_kwh_entity="sensor.tarif_heures_pleines_ttc",
    bands=[
        PriceBand(
            start_hour=0,
            end_hour=6,
            eur_kwh=0.21,
            eur_kwh_entity="sensor.tarif_heures_creuses_ttc",
        )
    ],
)
TEMPO = Tariff(
    kind=TariffKind.DAY_COLOR,
    base_eur_kwh=0.2,
    color_entity="sensor.tempo_today",
    colors=[
        ColorPrices(
            color="Bleu",
            base_eur_kwh=0.16,
            base_eur_kwh_entity="sensor.tarif_bleu_tempo_heures_pleines_ttc",
            bands=[
                PriceBand(
                    start_hour=22,
                    end_hour=24,
                    eur_kwh=0.13,
                    eur_kwh_entity="sensor.tarif_bleu_tempo_heures_creuses_ttc",
                )
            ],
        )
    ],
)


def state(entity_id: str, value: str) -> dict[str, object]:
    return {"entity_id": entity_id, "state": value, "attributes": {}}


def test_the_prices_come_from_the_entities() -> None:
    states = [
        state("sensor.tarif_heures_pleines_ttc", "0.2516"),
        state("sensor.tarif_heures_creuses_ttc", "0.1987"),
    ]
    assert needs_states(OFF_PEAK)
    context = tariff_context(OFF_PEAK, states, TODAY, PARIS)
    prices = OFF_PEAK.hourly(TODAY, context)

    assert prices[3] == 0.1987
    assert prices[12] == 0.2516


def test_an_unavailable_entity_keeps_the_entered_price() -> None:
    states = [
        state("sensor.tarif_heures_pleines_ttc", "unavailable"),
        state("sensor.tarif_heures_creuses_ttc", "0.1987"),
    ]
    prices = OFF_PEAK.hourly(TODAY, tariff_context(OFF_PEAK, states, TODAY, PARIS))

    assert prices[3] == 0.1987
    assert prices[12] == 0.27  # saisi
    assert OFF_PEAK.hourly(TODAY) == {h: 0.21 if h < 6 else 0.27 for h in range(24)}


def test_the_unit_factor_applies() -> None:
    tariff = OFF_PEAK.model_copy(update={"price_factor": 0.01})  # centimes/kWh
    states = [state("sensor.tarif_heures_pleines_ttc", "25.16")]

    assert tariff.hourly(TODAY, tariff_context(tariff, states, TODAY, PARIS))[12] == 0.2516


def test_the_color_prices_come_from_the_entities() -> None:
    states = [
        state("sensor.tempo_today", "Bleu"),
        state("sensor.tarif_bleu_tempo_heures_pleines_ttc", "0.1552"),
        state("sensor.tarif_bleu_tempo_heures_creuses_ttc", "0.1288"),
    ]
    prices = TEMPO.hourly(TODAY, tariff_context(TEMPO, states, TODAY, PARIS))

    assert prices[12] == 0.1552
    assert prices[23] == 0.1288


def test_the_export_entity_without_forecast_gives_its_state() -> None:
    tariff = Tariff(base_eur_kwh=0.25, export_eur_kwh=0.04, export_entity="sensor.rachat")
    context = tariff_context(tariff, [state("sensor.rachat", "0.1276")], TODAY, PARIS)

    assert tariff.export_hourly(TODAY, context) == dict.fromkeys(range(24), 0.1276)
    assert tariff.export_hourly(TODAY, TariffContext()) == dict.fromkeys(range(24), 0.04)


def test_the_entities_are_saved_and_read_back(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    for tariff in (OFF_PEAK, TEMPO):
        configuration.save(graph, Configuration(tariff=tariff))
        assert configuration.load(graph).tariff == tariff


def test_a_tariff_without_entity_does_not_read_home_assistant() -> None:
    plain = Tariff(kind=TariffKind.TIME_OF_USE, base_eur_kwh=0.27, bands=OFF_PEAK.bands[:0])
    assert not needs_states(plain)
    assert plain.price_entities() == []
    assert OFF_PEAK.price_entities() == [
        "sensor.tarif_heures_pleines_ttc",
        "sensor.tarif_heures_creuses_ttc",
    ]
