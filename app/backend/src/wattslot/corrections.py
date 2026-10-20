"""Corrections des agrégats (lot qualité, 1/3) : une table de la base, jamais les agrégats
eux-mêmes. ``Aggregator.read`` les applique à la lecture ; ``quality.py`` les crée.

Chaque correction garde le capteur, la période, la valeur d'origine et la valeur corrigée : de
quoi l'annuler, et plus tard la reporter dans le recorder de HA.
"""

import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from wattslot.aggregation import Aggregate


class Kind(StrEnum):
    SPIKE = "spike"
    NEGATIVE = "negative"
    GAP = "gap"


class Method(StrEnum):
    DISCARD = "discard"  # période retirée des lectures
    ESTIMATE = "estimate"  # moyenne des périodes voisines
    RAW = "raw"  # recalculée sur le relevé brut (gardé trois jours)


class Correction(BaseModel):
    id: int
    entity_id: str
    period: str
    start: datetime
    kind: Kind
    method: Method
    original_kwh: float | None
    corrected_kwh: float | None  # None : période écartée
    automatic: bool
    created_at: datetime
    undone_at: datetime | None = None


# --- Corrections -----------------------------------------------------------------------------


def _row(row: tuple[object, ...]) -> Correction:
    (
        id_,
        entity_id,
        period,
        start,
        kind,
        method,
        original,
        corrected,
        automatic,
        created,
        undone,
    ) = row
    return Correction(
        id=int(str(id_)),
        entity_id=str(entity_id),
        period=str(period),
        start=datetime.fromisoformat(str(start)),
        kind=Kind(str(kind)),
        method=Method(str(method)),
        original_kwh=None if original is None else float(str(original)),
        corrected_kwh=None if corrected is None else float(str(corrected)),
        automatic=bool(automatic),
        created_at=datetime.fromisoformat(str(created)),
        undone_at=None if undone is None else datetime.fromisoformat(str(undone)),
    )


COLUMNS = (
    "id, entity_id, period, start, kind, method, original_kwh, corrected_kwh, automatic, "
    "created_at, undone_at"
)


def _when(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class Target(Protocol):
    """Période à corriger (une anomalie de ``quality.py``)."""

    entity_id: str
    period: str
    start: datetime
    kind: Kind
    energy_kwh: float | None


class CorrectionStore:
    """Corrections des agrégats, dans la base de l'application."""

    def __init__(self, database: sqlite3.Connection) -> None:
        self._database = database

    def active(
        self, entity_id: str, period: str, start: datetime, end: datetime
    ) -> dict[datetime, Correction]:
        """Corrections en vigueur d'un capteur sur ``[start, end)``, par début de période."""
        rows = self._database.execute(
            f"SELECT {COLUMNS} FROM quality_corrections WHERE entity_id = ? AND period = ? "
            "AND start >= ? AND start < ? AND undone_at IS NULL",
            (entity_id, period, _when(start), _when(end)),
        ).fetchall()
        return {c.start: c for c in map(_row, rows)}

    def known(self, entity_id: str, period: str, start: datetime) -> bool:
        """Une correction, même annulée, existe pour cette période."""
        row = self._database.execute(
            "SELECT 1 FROM quality_corrections WHERE entity_id = ? AND period = ? AND start = ?",
            (entity_id, period, _when(start)),
        ).fetchone()
        return row is not None

    def list(self, undone: bool = False) -> list[Correction]:
        query = f"SELECT {COLUMNS} FROM quality_corrections"
        if not undone:
            query += " WHERE undone_at IS NULL"
        rows = self._database.execute(query + " ORDER BY start DESC, id DESC").fetchall()
        return [_row(row) for row in rows]

    def add(
        self,
        target: "Target",
        method: Method,
        corrected_kwh: float | None,
        automatic: bool,
        now: datetime | None = None,
    ) -> Correction:
        """Nouvelle correction d'une période ; celle qui était en vigueur est annulée."""
        moment = _when(now or datetime.now(UTC))
        with self._database:
            self._database.execute(
                "UPDATE quality_corrections SET undone_at = ? WHERE entity_id = ? AND period = ? "
                "AND start = ? AND undone_at IS NULL",
                (moment, target.entity_id, target.period, _when(target.start)),
            )
            cursor = self._database.execute(
                "INSERT INTO quality_corrections (entity_id, period, start, kind, method, "
                "original_kwh, corrected_kwh, automatic, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    target.entity_id,
                    target.period,
                    _when(target.start),
                    target.kind.value,
                    method.value,
                    target.energy_kwh,
                    corrected_kwh,
                    int(automatic),
                    moment,
                ),
            )
        row = self._database.execute(
            f"SELECT {COLUMNS} FROM quality_corrections WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row(row)

    def undo(self, correction_id: int, now: datetime | None = None) -> bool:
        """Annule une correction en vigueur ; False si elle n'existe pas ou l'est déjà."""
        with self._database:
            cursor = self._database.execute(
                "UPDATE quality_corrections SET undone_at = ? WHERE id = ? AND undone_at IS NULL",
                (_when(now or datetime.now(UTC)), correction_id),
            )
        return cursor.rowcount > 0


def apply(
    aggregates: "list[Aggregate]", corrections: dict[datetime, Correction]
) -> "list[Aggregate]":
    """Agrégats corrigés : écartés, ou énergie remplacée."""
    if not corrections:
        return aggregates
    found: list[Aggregate] = []
    for aggregate in aggregates:
        correction = corrections.get(aggregate.start)
        if correction is None:
            found.append(aggregate)
        elif correction.corrected_kwh is not None:
            found.append(aggregate.model_copy(update={"energy_kwh": correction.corrected_kwh}))
    return found
