"""Fusion passé/futur et bascule de minuit : la réécriture donne les mêmes résultats que la v1."""

import itertools
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tests.v1_oracle import v1
from wattslot.planning.cycles import Segment
from wattslot.planning.merge import merge_plans, start_soc
from wattslot.planning.rollover import next_rollover, seconds_until

DAY = date(2026, 10, 13)
NAMES = ["Chauffe-eau", "Lave-linge", "Sèche-linge", "Lave-vaisselle"]
PARIS = ZoneInfo("Europe/Paris")


def hourly(rng: random.Random) -> dict[int, float]:
    return {h: rng.uniform(-2, 2) for h in range(24) if rng.random() < 0.8}


def battery(rng: random.Random) -> dict[str, Any]:
    movements = [
        {"heure": h, "action": rng.choice(["charge", "decharge"]), "energie_kwh": rng.uniform(0, 1)}
        for h in range(24)
        if rng.random() < 0.4
    ]
    item: dict[str, Any] = {
        "equipement": "Batterie",
        "mouvements": movements,
        "soc_horaire_kwh": {h: rng.uniform(0, 5) for h in range(24) if rng.random() < 0.9},
        "priorite": 2,
    }
    for key in ("soc_initial_kwh", "soc_final_kwh"):
        if rng.random() < 0.8:
            item[key] = rng.uniform(0, 5)
    return item


def pool(rng: random.Random) -> dict[str, Any]:
    cuts = sorted(rng.sample(range(1, 24), rng.randint(0, 5)))
    bounds = [0, *cuts, 24]
    segments = [
        {"heure_debut": a, "heure_fin": b, "mode": rng.choice(["off", "silence", "eco"])}
        for a, b in itertools.pairwise(bounds)
    ]
    return {"equipement": "Piscine (filtration)", "segments": segments, "priorite": 4}


def plan(rng: random.Random, day: date) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if rng.random() < 0.9:
        items.append(battery(rng))
    if rng.random() < 0.9:
        items.append(pool(rng))
    for name in NAMES:
        if rng.random() < 0.5:
            start = rng.randint(0, 22)
            items.append(
                {
                    "equipement": name,
                    "heure_debut": start,
                    "heure_fin": start + 2,
                    "energie_kwh": rng.uniform(0.2, 2),
                }
            )
    warnings = [
        rng.choice([{"code": "a", "params": {"x": 1}}, {"code": "b", "params": {}}, "texte"])
        for _ in range(rng.randint(0, 3))
    ]
    result: dict[str, Any] = {
        "date_cible": day,
        "planning": items,
        "avertissements": warnings,
        "avertissements_prevision": warnings[:1],
        "taches_placees": [
            {"summary": n, "due": rng.choice([day.isoformat(), "2026-10-20"])}
            for n in NAMES
            if rng.random() < 0.3
        ],
        "taches_en_attente": [{"summary": n} for n in NAMES if rng.random() < 0.3],
    }
    for field in ("surplus_horaire", "net_horaire_signe", "residu_reseau_horaire"):
        result[field] = hourly(rng)
    return result


def real(rng: random.Random) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    for name in NAMES:
        if rng.random() < 0.3:
            start = datetime(2026, 10, 13, rng.randint(0, 20), tzinfo=PARIS)
            found[name] = [
                {
                    "debut_iso": start.isoformat(),
                    "fin_iso": (start + timedelta(minutes=90)).isoformat(),
                    "energie_kwh": rng.uniform(0, 2),
                    "en_cours": False,
                }
            ]
    return found


def segments(raw: dict[str, list[dict[str, Any]]]) -> dict[str, list[Segment]]:
    return {
        name: [
            Segment(
                datetime.fromisoformat(s["debut_iso"]),
                datetime.fromisoformat(s["fin_iso"]),
                s["energie_kwh"],
                s["en_cours"],
            )
            for s in segs
        ]
        for name, segs in raw.items()
    }


def by_name(merged: dict[str, Any]) -> dict[str, Any]:
    return {**merged, "planning": sorted(merged["planning"], key=lambda i: i["equipement"])}


@pytest.mark.parametrize("seed", range(400))
def test_merge_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    new = plan(rng, DAY)
    old = rng.choice([None, plan(rng, DAY), plan(rng, DAY), plan(rng, DAY - timedelta(days=1))])
    first_hour = rng.randint(0, 23)
    raw = real(rng) if rng.random() < 0.7 else {}

    expected = v1("fusion_planning.fusionner_etats", new, old, first_hour, raw)
    actual = merge_plans(new, old, first_hour, segments(raw))

    assert by_name(actual) == by_name(expected)


def test_an_old_warning_about_a_device_now_placed_is_dropped() -> None:
    missing = {"code": "profil_indisponible_attente", "params": {"equipement": "Chauffe-Eau"}}
    other = {"code": "profil_indisponible_attente", "params": {"equipement": "Lave Linge"}}
    old = {"date_cible": DAY, "planning": [], "avertissements": [missing, other, "texte"]}
    heater = {"equipement": "Chauffe-Eau", "heure_debut": 3, "heure_fin": 6, "energie_kwh": 1.7}
    new = {"date_cible": DAY, "planning": [heater], "avertissements": []}

    merged = merge_plans(new, old, 2)

    # Le chauffe-eau est placé : son ancien avertissement est périmé ; les autres restent.
    assert merged["avertissements"] == [other, "texte"]


@pytest.mark.parametrize("seed", range(300))
def test_start_soc_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    hour = rng.randint(0, 23)
    readings: dict[str, Any] = {}
    if rng.random() < 0.8:
        readings["soc_pct_minuit"] = rng.uniform(10, 100)
    if rng.random() < 0.9:
        readings["soc_pct_fin_heure"] = {
            rng.choice([h, str(h)]): rng.uniform(10, 100) for h in range(24) if rng.random() < 0.8
        }
    if rng.random() < 0.8:
        at = datetime(2026, 10, 13, rng.choice([hour, (hour + 1) % 24]), rng.randint(0, 59))
        readings["heure_maj_iso"] = rng.choice([at.isoformat(), "illisible"])
    old: dict[str, Any] | None = None
    if rng.random() < 0.8:
        old = {
            "planning": [battery(rng)] if rng.random() < 0.9 else [],
            "capacite_batterie_kwh": rng.choice([0, rng.uniform(2, 10)]),
            "rendement_round_trip_percent": rng.choice([None, rng.uniform(70, 95)]),
        }
        if rng.random() < 0.5:
            old["rendements_batterie"] = {
                "status": rng.choice(["ok", "insuffisant"]),
                "rendement_charge_percent": rng.uniform(70, 100),
                "rendement_decharge_percent": rng.uniform(70, 100),
            }

    assert start_soc(readings, hour, old) == v1(
        "fusion_planning.soc_depart_calcul_pct", readings, hour, old
    )


@pytest.mark.parametrize("seed", range(300))
def test_rollover_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    now = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=rng.randint(0, 366 * 86_400))
    if rng.random() < 0.2:  # autour des changements d'heure et de minuit
        now = rng.choice(
            [
                datetime(2026, 3, 28, 23, 0, 30, tzinfo=UTC),
                datetime(2026, 10, 24, 22, 0, 59, tzinfo=UTC),
            ]
        )

    expected = v1("bascule_jour.prochaine_bascule", now)
    actual = next_rollover(now, PARIS)

    assert actual == expected
    assert seconds_until(actual, now) == v1("bascule_jour.secondes_avant", expected, now)
