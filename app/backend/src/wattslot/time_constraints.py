"""Contraintes horaires d'un équipement (lot 3.5).

Trois sortes, chacune **dure** (par défaut : jamais violée, l'équipement n'est pas placé si
aucun créneau ne la respecte) ou **souple** (violée au prix d'une pénalité, signalée) :

- **plage interdite** ``[start_hour, end_hour)``, à cheval sur minuit si ``start_hour >
  end_hour`` (pas de sèche-linge de 22 h à 7 h) ;
- **pas avant** ``start_hour`` ;
- **terminé avant** ``end_hour`` (linge terminé avant 18 h).

Elles valent pour les cycles à démarrer, les besoins d'énergie et les durées à placer. Une
contrainte qui ne tient pas est signalée en la nommant, jamais ignorée en silence.
"""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, Field
from pyoxigraph import BlankNode, Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, XSD_BOOLEAN, vocab
from wattslot.storage.graph import GraphStore

XSD_INTEGER = NamedNode("http://www.w3.org/2001/XMLSchema#integer")
DAY_MIN = 24 * 60


class ConstraintKind(StrEnum):
    FORBIDDEN = "forbidden"
    NOT_BEFORE = "not_before"
    FINISH_BEFORE = "finish_before"


class TimeConstraint(BaseModel):
    kind: ConstraintKind
    start_hour: int = Field(default=0, ge=0, le=23)  # plage interdite, pas avant
    end_hour: int = Field(default=24, ge=1, le=24)  # plage interdite (exclue), terminé avant
    hard: bool = True

    def blocked(self) -> list[tuple[int, int]]:
        """Intervalles de la journée (minutes, fin exclue) où l'équipement ne doit pas tourner."""
        start, end = self.start_hour * 60, self.end_hour * 60
        if self.kind is ConstraintKind.NOT_BEFORE:
            return [(0, start)] if start > 0 else []
        if self.kind is ConstraintKind.FINISH_BEFORE:
            return [(end, DAY_MIN)] if end < DAY_MIN else []
        if start < end:
            return [(start, end)]
        if start > end:
            return [(start, DAY_MIN), (0, end)]
        return []

    def blocks(self, start_min: int, end_min: int) -> bool:
        """L'intervalle ``[start_min, end_min)`` déborde sur une période interdite."""
        return any(start_min < b_end and b_start < end_min for b_start, b_end in self.blocked())

    def label(self) -> str:
        """Notation courte, sans langue, pour les avertissements : « 22h-7h », « ≥9h », « ≤18h »."""
        if self.kind is ConstraintKind.NOT_BEFORE:
            return f"≥{self.start_hour}h"
        if self.kind is ConstraintKind.FINISH_BEFORE:
            return f"≤{self.end_hour}h"
        return f"{self.start_hour}h-{self.end_hour}h"


def labels(constraints: Sequence[TimeConstraint]) -> str:
    return ", ".join(c.label() for c in constraints)


def problems(constraints: Sequence[TimeConstraint]) -> list[tuple[str, dict[str, str]]]:
    found: list[tuple[str, dict[str, str]]] = []
    for c in constraints:
        if c.kind is ConstraintKind.FORBIDDEN and c.start_hour == c.end_hour:
            found.append(("constraint_range_empty", {"constraint": c.label()}))
    hard = [c for c in constraints if c.hard]
    if hard and all(any(c.blocks(m, m + 60) for c in hard) for m in range(0, DAY_MIN, 60)):
        found.append(("constraints_leave_no_time", {}))
    return found


# --- Graphe ----------------------------------------------------------------------------------


def _integer(value: int) -> Literal:
    return Literal(str(value), datatype=XSD_INTEGER)


def to_triples(owner: NamedNode, constraints: Sequence[TimeConstraint]) -> list[Triple]:
    prefix = owner.value.rsplit("/", 1)[-1]
    triples = []
    for index, c in enumerate(constraints):
        node = BlankNode(f"{prefix}constraint{index}")
        triples += [
            Triple(owner, vocab("hasTimeConstraint"), node),
            Triple(node, RDF_TYPE, vocab("TimeConstraint")),
            Triple(node, vocab("order"), _integer(index)),
            Triple(node, vocab("constraintKind"), Literal(c.kind.value)),
            Triple(node, vocab("constraintStartHour"), _integer(c.start_hour)),
            Triple(node, vocab("constraintEndHour"), _integer(c.end_hour)),
            Triple(node, vocab("hard"), Literal(str(c.hard).lower(), datatype=XSD_BOOLEAN)),
        ]
    return triples


def load(graph: GraphStore, graph_iri: str, owner: str, vocab_ns: str) -> list[TimeConstraint]:
    rows = graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?order ?kind ?start ?end ?hard WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner}> wattslot:hasTimeConstraint ?node .
            ?node wattslot:order ?order ; wattslot:constraintKind ?kind ;
              wattslot:constraintStartHour ?start ;
              wattslot:constraintEndHour ?end ; wattslot:hard ?hard .
          }}
        }}
        """
    )
    return [
        TimeConstraint(
            kind=ConstraintKind(row["kind"]),
            start_hour=int(row["start"]),
            end_hour=int(row["end"]),
            hard=row["hard"] == "true",
        )
        for row in sorted(rows, key=lambda r: int(r["order"]))
    ]
