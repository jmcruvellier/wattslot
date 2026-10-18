"""Tempo, prix dynamique et détection depuis le tableau Énergie (lot 3.2)."""

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.energy import energy_sources
from wattslot.main import create_app
from wattslot.planning.tariff_sources import needs_states, tariff_context
from wattslot.storage.graph import GraphStore
from wattslot.tariff import (
    ColorPrices,
    PriceBand,
    Tariff,
    TariffContext,
    TariffKind,
    off_peak_ranges,
    problems,
    propose,
)

PARIS = ZoneInfo("Europe/Paris")
TODAY, TOMORROW, LATER = date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18)


def color(name: str, peak: float, off_peak: float) -> ColorPrices:
    return ColorPrices(
        color=name,
        base_eur_kwh=peak,
        bands=[
            PriceBand(start_hour=0, end_hour=6, eur_kwh=off_peak),
            PriceBand(start_hour=22, end_hour=24, eur_kwh=off_peak),
        ],
    )


TEMPO = Tariff(
    kind=TariffKind.DAY_COLOR,
    base_eur_kwh=0.2,
    colors=[color("Bleu", 0.16, 0.13), color("Blanc", 0.19, 0.15), color("Rouge", 0.76, 0.16)],
    color_entity="sensor.tempo_today",
    color_tomorrow_entity="sensor.tempo_tomorrow",
    color_day_start_hour=6,
)
DYNAMIC = Tariff(
    kind=TariffKind.DYNAMIC,
    base_eur_kwh=0.3,
    price_entity="sensor.spot",
    export_entity="sensor.spot_export",
    price_factor=0.001,  # €/MWh
)


def state(entity_id: str, value: str, **attributes: object) -> dict[str, object]:
    return {"entity_id": entity_id, "state": value, "attributes": attributes}


def test_tempo_colors_from_home_assistant_with_a_day_starting_at_six() -> None:
    states = [state("sensor.tempo_today", "Blanc"), state("sensor.tempo_tomorrow", "red")]
    context = tariff_context(TEMPO, states, TODAY, PARIS)

    assert context.colors == {TODAY: "Blanc", TOMORROW: "red"}
    today = TEMPO.hourly(TODAY, context)
    assert today[5] == 0.13  # avant 6 h : couleur de la veille, inconnue → la première (bleu)
    assert today[6] == 0.19 and today[22] == 0.15  # blanc
    tomorrow = TEMPO.hourly(TOMORROW, context)
    assert tomorrow[3] == 0.15 and tomorrow[12] == 0.76 and tomorrow[23] == 0.16  # rouge
    assert TEMPO.hourly(LATER, context)[12] == 0.16  # au-delà : bleu
    assert off_peak_ranges(TEMPO, TOMORROW, context) == [(0, 6), (22, 24)]

    unknown = tariff_context(TEMPO, [state("sensor.tempo_today", "unavailable")], TODAY, PARIS)
    assert unknown.colors == {}


def test_dynamic_prices_in_several_formats() -> None:
    nordpool = state(
        "sensor.spot",
        "120",
        raw_today=[
            {
                "start": "2026-10-16T10:00:00+02:00",
                "end": "2026-10-16T11:00:00+02:00",
                "value": 100,
            },
            {"start": "2026-10-16T11:00:00+02:00", "end": "2026-10-16T12:00:00+02:00", "value": 40},
        ],
        # Quarts d'heure (ENTSO-e) : moyennés par heure.
        raw_tomorrow=[
            {"time": "2026-10-17T07:00:00Z", "price": 80},
            {"time": "2026-10-17T07:15:00Z", "price": 120},
        ],
    )
    tibber = state(
        "sensor.spot_export",
        "0.05",
        prices=[{"startsAt": "2026-10-16T12:00:00+02:00", "total": 60}],
    )
    context = tariff_context(DYNAMIC, [nordpool, tibber], TODAY, PARIS)

    today = DYNAMIC.hourly(TODAY, context)
    assert today[10] == 0.1 and today[11] == 0.04 and today[12] == 0.3  # inconnue : prix de base
    assert DYNAMIC.hourly(TOMORROW, context)[9] == 0.1  # 7 h UTC = 9 h à Paris
    export = DYNAMIC.export_hourly(TODAY, context)
    assert export[12] == 0.06 and export[13] == 0.0
    assert needs_states(DYNAMIC) and not needs_states(Tariff(base_eur_kwh=0.2))


def test_problems_of_the_new_kinds() -> None:
    assert problems(TEMPO) == [] and problems(DYNAMIC) == []
    empty_tempo = Tariff(kind=TariffKind.DAY_COLOR, base_eur_kwh=0.2)
    assert [code for code, _ in problems(empty_tempo)] == [
        "tariff_without_colors",
        "tariff_without_color_entity",
    ]
    twice = TEMPO.model_copy(update={"colors": [color("Bleu", 1, 1), color("blue", 1, 1)]})
    assert [code for code, _ in problems(twice)] == ["color_twice"]
    empty_dynamic = Tariff(kind=TariffKind.DYNAMIC, base_eur_kwh=0.2)
    assert [code for code, _ in problems(empty_dynamic)] == ["tariff_without_price_entity"]


def test_saved_and_read_back(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    for tariff in (TEMPO, DYNAMIC):
        configuration.save(graph, Configuration(tariff=tariff))
        assert configuration.load(graph).tariff == tariff


def test_prices_of_the_energy_dashboard() -> None:
    current = energy_sources(
        {
            "energy_sources": [
                {
                    "type": "grid",
                    "stat_energy_from": "sensor.import",
                    "stat_energy_to": "sensor.export",
                    "entity_energy_price": "sensor.spot",
                    "number_energy_price_export": 0.06,
                }
            ]
        }
    ).grid
    assert (current.import_price_entity, current.export_price) == ("sensor.spot", 0.06)
    legacy = energy_sources(
        {
            "energy_sources": [
                {
                    "type": "grid",
                    "flow_from": [{"stat_energy_from": "sensor.a", "number_energy_price": 0.2}],
                    "flow_to": [{"stat_energy_to": "sensor.b", "entity_energy_price": "sensor.x"}],
                }
            ]
        }
    ).grid
    assert (legacy.import_price, legacy.export_price_entity) == (0.2, "sensor.x")

    dynamic = propose(None, "sensor.spot", 0.06, None)
    assert dynamic is not None and dynamic.kind is TariffKind.DYNAMIC
    assert (dynamic.price_entity, dynamic.export_eur_kwh) == ("sensor.spot", 0.06)
    assert propose(0.2, None, None, "sensor.x") == Tariff(
        base_eur_kwh=0.2, export_entity="sensor.x"
    )
    assert propose(None, None, None, None) is None


def test_proposal_route_needs_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/configuration/tariff-proposal").status_code == 503


def test_context_is_empty_without_states() -> None:
    assert tariff_context(TEMPO, [], TODAY, PARIS) == TariffContext()


def test_the_input_reads_the_day_color_from_home_assistant(tmp_path: Path) -> None:
    import asyncio

    from tests.planning.test_assemble import MODEL, client, local
    from tests.planning.test_assemble import TODAY as DAY
    from tests.planning.test_runner import answers, context, reader_with_history
    from wattslot.planning.assemble import build_input
    from wattslot.planning.journal import CycleJournal
    from wattslot.planning.problem import from_input

    replies = answers()
    states = list(replies["get_states"])  # type: ignore[call-overload]
    replies["get_states"] = [*states, state("sensor.tempo_today", "Rouge")]
    ctx = context(tmp_path, reader_with_history())
    journal = CycleJournal(ctx.database, ctx.raw, ctx.reader)

    data = asyncio.run(
        build_input(
            DAY,
            local(DAY, 9, 20),
            client(replies),
            MODEL,
            ctx.reader,
            ctx.raw,
            journal,
            ctx.settings,
            None,
            Configuration(tariff=TEMPO),
        )
    )

    assert data.tariff_context.colors == {DAY: "Rouge"}
    assert from_input(data).prices_eur_kwh[12] == 0.76
