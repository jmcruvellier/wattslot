"""Disposition du dashboard (lot 5.5) : ordre et cartes masquées de
chaque vue, indicateur mis en avant et indicateurs masqués.

Gardée dans l'installation (``app_settings``, point n° 4) : la même sur tous les navigateurs du
foyer. Une carte n'apparaît que si l'installation la justifie (lot 5.3) **et** si elle n'est pas
masquée ; la disposition ne fait que changer l'ordre et la visibilité du catalogue. Une carte
ajoutée plus tard au catalogue prend sa place par défaut dans une disposition déjà enregistrée.
"""

import json
import sqlite3
from typing import Literal, Self

from fastapi import APIRouter, Request
from pydantic import BaseModel, model_validator

LAYOUT_KEY = "dashboard_layout"

# Catalogue des cartes de chaque vue, dans l'ordre par défaut (celui de l'interface).
DAY_CARDS = ("summary", "timeline", "soc", "grid", "energy", "indicators", "explanations")
WEEK_CARDS = ("production", "consumption", "soc", "days")
CATALOG: dict[str, tuple[str, ...]] = {
    "yesterday": DAY_CARDS,
    "today": DAY_CARDS,
    "tomorrow": DAY_CARDS,
    "week": WEEK_CARDS,
}

IndicatorKey = Literal[
    "cost_eur",
    "import_kwh",
    "export_kwh",
    "self_consumption_percent",
    "co2_kg",
    "end_soc_percent",
    "battery_throughput_kwh",
]


class ViewLayout(BaseModel):
    order: list[str] = []  # cartes du catalogue ; les absentes prennent leur place par défaut
    hidden: list[str] = []


class IndicatorLayout(BaseModel):
    highlight: IndicatorKey | None = None  # aucun : celui de l'objectif du calcul
    hidden: list[IndicatorKey] = []

    @model_validator(mode="after")
    def _no_duplicate(self) -> Self:
        if len(set(self.hidden)) != len(self.hidden):
            raise ValueError("indicateur masqué en double")
        if self.highlight is not None and self.highlight in self.hidden:
            raise ValueError("l'indicateur mis en avant est masqué")
        return self


class DashboardLayout(BaseModel):
    yesterday: ViewLayout = ViewLayout()
    today: ViewLayout = ViewLayout()
    tomorrow: ViewLayout = ViewLayout()
    week: ViewLayout = ViewLayout()
    indicators: IndicatorLayout = IndicatorLayout()

    @model_validator(mode="after")
    def _known_cards(self) -> Self:
        for view, cards in CATALOG.items():
            layout: ViewLayout = getattr(self, view)
            for field in ("order", "hidden"):
                values: list[str] = getattr(layout, field)
                unknown = sorted(set(values) - set(cards))
                if unknown:
                    raise ValueError(f"{view}.{field} : cartes inconnues {unknown}")
                if len(set(values)) != len(values):
                    raise ValueError(f"{view}.{field} : carte en double")
        return self


class LayoutResponse(DashboardLayout):
    """Disposition complète : chaque ordre contient toutes les cartes du catalogue."""

    default: bool = True  # aucune personnalisation enregistrée


def complete_order(order: list[str], catalog: tuple[str, ...]) -> list[str]:
    """Ordre enregistré, plus les cartes du catalogue qui n'y sont pas, chacune placée juste
    après celle qui la précède dans l'ordre par défaut (en tête pour la première)."""
    found = [card for card in order if card in catalog]
    for index, card in enumerate(catalog):
        if card not in found:
            found.insert(found.index(catalog[index - 1]) + 1 if index else 0, card)
    return found


def load_layout(database: sqlite3.Connection) -> DashboardLayout | None:
    row = database.execute("SELECT value FROM app_settings WHERE key = ?", (LAYOUT_KEY,)).fetchone()
    return DashboardLayout.model_validate(json.loads(row[0])) if row else None


def save_layout(database: sqlite3.Connection, layout: DashboardLayout) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (LAYOUT_KEY, layout.model_dump_json()),
        )


def reset_layout(database: sqlite3.Connection) -> None:
    with database:
        database.execute("DELETE FROM app_settings WHERE key = ?", (LAYOUT_KEY,))


def response(layout: DashboardLayout | None) -> LayoutResponse:
    found = layout or DashboardLayout()
    views = {
        view: ViewLayout(
            order=complete_order(getattr(found, view).order, cards),
            hidden=getattr(found, view).hidden,
        )
        for view, cards in CATALOG.items()
    }
    return LayoutResponse(**views, indicators=found.indicators, default=layout is None)


router = APIRouter()


@router.get("/api/settings/dashboard")
def get_dashboard_layout(request: Request) -> LayoutResponse:
    """Disposition du dashboard : celle enregistrée, complétée, ou celle par défaut."""
    return response(load_layout(request.app.state.database))


@router.put("/api/settings/dashboard")
def put_dashboard_layout(request: Request, layout: DashboardLayout) -> LayoutResponse:
    save_layout(request.app.state.database, layout)
    return response(layout)


@router.delete("/api/settings/dashboard")
def delete_dashboard_layout(request: Request) -> LayoutResponse:
    """« Revenir à la disposition par défaut » : la composition selon l'installation."""
    reset_layout(request.app.state.database)
    return response(None)
