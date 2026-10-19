"""Vue Semaine (lot 5.1, PR 4) : mêmes cartes et mêmes séries que ``dashboard_semaine.py`` de la
v1 d'origine, sur un horizon fait des états de référence."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.test_views_day import V1_CONTEXT, actual_of, state_of
from tests.v1_oracle import STATES, v1
from wattslot.main import create_app
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database
from wattslot.views import week

CONTEXT = replace(V1_CONTEXT, off_peak=((0, 6), (22, 24)))  # heures creuses de la v1


def horizon_of(count: int = 4) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Horizon de ``count`` jours consécutifs faits des états de référence, et le plan du jour
    (la veille du premier jour)."""
    first = state_of(STATES[0])["date_cible"]
    days = [
        {**state_of(path), "date_cible": first + timedelta(days=i + 1)}
        for i, path in enumerate(STATES[1 : count + 1])
    ]
    return {"jours": days, "avertissements": [], "duree_s": 12.0}, days


def test_day_cards_and_series_are_those_of_the_v1() -> None:
    _, days = horizon_of()

    for state in days:
        expected = v1("dashboard_semaine.resume_jour", state)
        found = week.day_summary(state, CONTEXT)
        for key in (
            "production_kwh",
            "soc_debut_pct",
            "soc_fin_pct",
            "soc_max_pct",
            "soutirage_kwh",
            "soutirage_hp_kwh",
            "injection_kwh",
        ):
            assert (
                found[key] == pytest.approx(expected[key])
                if expected[key] is not None
                else found[key] is None
            )
        assert [i["equipement"] for i in found["equipements"]] == [
            i["equipement"] for i in expected["equipements"]
        ]
    assert week.hourly_points(days, CONTEXT) == v1("dashboard_semaine.series_horaires", days)


def test_today_is_realigned_on_the_actual_data_as_in_its_view() -> None:
    horizon, _ = horizon_of()
    today = state_of(STATES[0])
    today["donnees_reelles_cache"] = actual_of(today, hour=14)
    # ``_recaler_aujourdhui`` de la v1 recale le résumé et les séries du jour sur le réel.
    expected_summary, expected_points = v1("dashboard_semaine.aujourdhui_recale", today)

    view = week.build_week(horizon, None, today, CONTEXT)

    first = view.days[0]
    assert (first.day, first.detail_view) == (today["date_cible"], "today")
    assert view.days[1].detail_view == "tomorrow" and view.days[2].detail_view is None
    assert first.soc_end_percent == pytest.approx(round(expected_summary["soc_fin_pct"], 1))
    assert first.production_kwh == pytest.approx(expected_summary["production_kwh"], abs=1e-3)
    assert [p.soc_percent for p in view.points[:24]] == [p["pct"] for p in expected_points]
    assert [p.consumption_kwh for p in view.points[:24]] == [
        p["consommation"] for p in expected_points
    ]
    assert len(view.points) == 24 * 5 and view.seconds == 12.0
    assert view.now_index == pytest.approx(13 + 20 / 60, abs=1e-3)


def test_tomorrow_replaces_the_first_day_of_the_horizon() -> None:
    horizon, days = horizon_of()
    tomorrow = {**days[0], "avertissements": [{"code": "horizon_interrompu", "params": {}}]}

    content = week.with_tomorrow_up_to_date(horizon, tomorrow)
    assert content["jours"][0] is tomorrow
    assert week.with_tomorrow_up_to_date(horizon, {**tomorrow, "date_cible": None}) == horizon
    view = week.build_week(horizon, tomorrow, None, CONTEXT)
    assert [n.code for n in view.days[0].notices] == ["horizon_interrompu"]


def test_the_v2_horizon_starts_after_tomorrow() -> None:
    """Le calcul n'enregistre que J+2…J+6 dans l'horizon (``runner.py``) : constat du 18/10/2026,
    la semaine commençait au 20, sans aujourd'hui ni demain, et le 20 portait « Demain »."""
    _, days = horizon_of(4)
    today = state_of(STATES[0])
    today["donnees_reelles_cache"] = actual_of(today, hour=8)
    tomorrow, after = days[0], days[1:]
    horizon = {"jours": after, "avertissements": [], "duree_s": 12.0}

    view = week.build_week(horizon, tomorrow, today, CONTEXT)

    assert [d.day for d in view.days] == [today["date_cible"], *(d["date_cible"] for d in days)]
    assert [d.detail_view for d in view.days[:3]] == ["today", "tomorrow", None]
    assert len(view.points) == 24 * 5 and view.now_index is not None
    without_tomorrow = week.build_week(horizon, None, today, CONTEXT)
    assert [d.day for d in without_tomorrow.days] == [d["date_cible"] for d in after]


def test_the_days_the_horizon_did_not_reach_are_listed() -> None:
    """Horizon arrêté (lot 7.3) : le jour sans plan et les suivants, jusqu'au dernier jour prévu
    (J+6), sont listés pour être affichés sans données."""
    _, days = horizon_of(4)
    today = state_of(STATES[0])
    day = today["date_cible"]
    stop = day + timedelta(days=5)
    horizon = {
        "jours": days[1:],
        "avertissements": [
            {"code": "horizon_sans_solution", "params": {"jour": stop.isoformat(), "raison": "x"}}
        ],
        "duree_s": 12.0,
        "derniere_execution": {"heure_iso": f"{day.isoformat()}T20:59:00+02:00", "manuel": False},
    }

    view = week.build_week(horizon, days[0], today, CONTEXT)

    assert view.days[-1].day == day + timedelta(days=4)
    assert view.missing_days == [stop, day + timedelta(days=6)]
    assert [n.code for n in view.notices] == ["horizon_sans_solution"]
    assert view.notices[0].text.startswith("Pas de plan à partir du")
    full = week.build_week({**horizon, "avertissements": []}, days[0], today, CONTEXT)
    assert full.missing_days == []


def test_route(tmp_path: Path) -> None:
    horizon, days = horizon_of(2)
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/views/week").status_code == 404
        PlanStore(open_database(tmp_path / "data")).save(
            "horizon", days[0]["date_cible"], horizon, 1.0, False
        )
        found = api.get("/api/views/week").json()

    assert [d["day"] for d in found["days"]] == [d["date_cible"].isoformat() for d in days]
    assert len(found["points"]) == 48


def test_versions(tmp_path: Path) -> None:
    horizon, days = horizon_of(2)
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/views/versions").json() == {
            "yesterday": None,
            "today": None,
            "tomorrow": None,
            "week": None,
        }
        store = PlanStore(open_database(tmp_path / "data"))
        store.save("horizon", days[0]["date_cible"], horizon, 1.0, False)
        store.save("today", days[0]["date_cible"], days[0], 1.0, False)
        found = api.get("/api/views/versions").json()

    assert found["today"] is not None and found["week"] >= found["today"]
    assert found["yesterday"] is None
