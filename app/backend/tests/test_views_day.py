"""Vues des jours (lot 5.1) : mêmes nombres que le dashboard de la v1 d'origine (résultats figés),
sur les 13 journées types, avec et sans données réelles."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.v1_oracle import STATES, load, v1
from wattslot.battery_settings import BatterySettings
from wattslot.main import create_app
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database
from wattslot.views import display
from wattslot.views.day import build_day
from wattslot.views.display import Context

IDS = [p.stem for p in STATES]
PARIS = ZoneInfo("Europe/Paris")
# Réglages de la v1 : plancher de 12 %, plage active de 6 h à 24 h, vitesses de la filtration.
V1_CONTEXT = Context(
    zone=PARIS, battery=BatterySettings(floor_percent=12, active_from_hour=6, active_to_hour=24)
)


def state_of(path: Path) -> dict[str, Any]:
    entree, sortie = load(path)
    return {**entree, **sortie}


def actual_of(state: dict[str, Any], hour: int = 14) -> dict[str, Any]:
    """Données réelles plausibles jusqu'à ``hour`` h 20 : production 10 % au-dessus de la
    prévision, SoC 3 points au-dessus du plan, premier cycle prévu lancé 30 min en retard et
    encore en cours."""
    day = state["date_cible"]
    now = datetime.combine(day, datetime.min.time(), PARIS) + timedelta(hours=hour, minutes=20)
    production = state.get("production_solaire_horaire") or {}
    battery = display.find_item(state["planning"], "Batterie")
    capacity = state.get("capacite_batterie_kwh") or 1.0
    soc = (
        {
            h: min(100.0, battery["soc_horaire_kwh"].get(h, 0) / capacity * 100 + 3)
            for h in range(hour + 1)
        }
        if battery
        else {}
    )
    segments: dict[str, list[dict[str, Any]]] = {}
    cycle = next(
        (i for i in state["planning"] if "heure_debut" in i and i["equipement"] != "Batterie"),
        None,
    )
    if cycle is not None and cycle["heure_debut"] < hour:
        start = datetime.combine(day, datetime.min.time(), PARIS) + timedelta(
            minutes=cycle.get("debut_min", cycle["heure_debut"] * 60) + 30
        )
        segments[cycle["equipement"]] = [
            {
                "debut_iso": start.isoformat(),
                "fin_iso": now.isoformat(),
                "energie_kwh": round(cycle.get("energie_kwh", 1.0) * 0.6, 3),
                "en_cours": True,
            }
        ]
    return {
        "heure_maj_iso": now.isoformat(),
        "production_reelle_horaire": {h: production.get(h, 0) * 1.1 for h in range(hour)},
        "soc_pct_fin_heure": soc,
        "equipements_reels_horaire": segments,
    }


@pytest.mark.parametrize("with_actual", [False, True], ids=["prévu", "réel"])
@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_series_and_summary_are_those_of_the_v1(path: Path, with_actual: bool) -> None:
    state = state_of(path)
    actual = actual_of(state) if with_actual else None
    view = build_day({**state, "donnees_reelles_cache": actual}, "today", V1_CONTEXT)

    soc, production, baseline, planned = v1("dashboard._courbe_soc_affichee", state, actual)
    assert [h.production_kwh for h in view.hours] == production
    for h in range(24):
        point = view.hours[h]
        assert point.consumption_kwh == pytest.approx(
            round(baseline.get(h, 0) + planned.get(h, 0), 3), abs=1e-9
        )
        if point.soc_percent is not None:
            assert point.soc_percent == pytest.approx(soc[h], abs=1e-9)
        exchange = -round(state.get("residu_reseau_horaire", {}).get(h, 0), 3)
        assert point.grid_import_kwh == round(max(exchange, 0), 3)
        assert point.grid_export_kwh == round(max(-exchange, 0), 3)

    expected = v1("dashboard._resume_journee", state, soc)
    # Totaux arrondis au Wh : la somme des flottants de Python 3.12 (compensée) peut changer le
    # dernier chiffre par rapport aux résultats figés de la v1, calculés en 3.11.
    assert view.summary.model_dump() == pytest.approx(
        {
            "soc_end_kwh": expected["soc_final_kwh"],
            "soc_end_percent": expected["soc_final_pct"],
            "soc_max_kwh": expected["soc_max_kwh"],
            "soc_max_percent": expected["soc_max_pct"],
            "soc_max_hour": expected["heure_soc_max"],
            "charge_kwh": expected["charge_total"],
            "discharge_kwh": expected["decharge_total"],
            "grid_import_kwh": expected["soutire_total"],
            "grid_export_kwh": expected["injecte_total"],
            "production_kwh": expected["production_totale"],
        },
        abs=1.001e-3,
    )
    recalculated = v1("dashboard._production_recalee", production, actual)
    assert view.production_recalculated_kwh == (
        pytest.approx(recalculated) if recalculated is not None else None
    )
    assert (
        display.initial_forecast_summary(state)["soc_end_kwh"]
        == (v1("dashboard.resume_prevision_initiale", state)["soc_final_kwh"])
    )


def test_tomorrow_ignores_actual_data() -> None:
    state = state_of(STATES[0])
    view = build_day({**state, "donnees_reelles_cache": actual_of(state)}, "tomorrow", V1_CONTEXT)

    assert view.actual_updated_at is None and view.initial_forecast is None
    assert view.battery_floor_percent == 12
    assert all(h.production_actual_kwh is None for h in view.hours)


def test_route(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/views/today").status_code == 404
        assert api.get("/api/views/someday").status_code == 422
        state = state_of(STATES[0])
        state["indicateurs"] = {"cout_eur": 1.23, "soutirage_kwh": 4.5, "injection_kwh": 0.7}
        PlanStore(open_database(tmp_path / "data")).save(
            "today", date(2026, 10, 12), state, 1.0, False
        )
        found = api.get("/api/views/today").json()
        # Sans objectif dans la configuration : celui du réglage du calcul.
        settings = api.get("/api/settings/planning").json()
        api.put("/api/settings/planning", json={**settings, "objective": "import"})
        autonomy = api.get("/api/views/today").json()["objective"]

    assert found["kind"] == "today" and len(found["hours"]) == 24
    assert found["objective"] == "cost" and autonomy == "autonomy"
    assert found["indicators"]["cost_eur"] == 1.23 and found["indicators"]["import_kwh"] == 4.5
    assert found["summary"]["production_kwh"] > 0
