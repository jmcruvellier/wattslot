"""Récurrence d'un cycle à démarrer, dans la configuration (lot 3.5).

Règle RFC 5545, même sous-ensemble que les tâches de HA (``planning/recurrence.py``) :

- **quotidienne avec intervalle** (``FREQ=DAILY;INTERVAL=2``) : comptée depuis le **dernier cycle
  réel** de l'équipement (journal des cycles), comme une tâche de HA recalée quand on la coche ;
- **hebdomadaire** (``FREQ=WEEKLY;BYDAY=TU,FR``) : sur le calendrier, semaines comptées depuis
  ``start`` quand ``INTERVAL`` dépasse 1.

Une occurrence manquée reste due jusqu'au prochain cycle réel (rattrapage), comme une tâche de HA
non cochée. Pour un équipement réglé ainsi, les tâches récurrentes de HA sont ignorées : la
liste de HA ne sert plus qu'aux demandes ponctuelles.
"""

from datetime import date, timedelta

from pydantic import BaseModel
from pyoxigraph import Literal, NamedNode, Triple

from wattslot.home_model import RDF_TYPE, vocab
from wattslot.planning.recurrence import UnsupportedRule, occurrences, parse_rule
from wattslot.storage.graph import GraphStore

XSD_DATE = NamedNode("http://www.w3.org/2001/XMLSchema#date")


class Recurrence(BaseModel):
    rule: str  # RFC 5545 : FREQ=DAILY ou WEEKLY, INTERVAL, BYDAY, UNTIL
    start: date | None = None  # hebdomadaire : semaine de départ de l'intervalle


def problems(recurrence: Recurrence) -> list[tuple[str, dict[str, str]]]:
    try:
        parse_rule(recurrence.rule)
    except UnsupportedRule as error:
        return [("recurrence_rule", {"rule": recurrence.rule, "reason": str(error)})]
    return []


def next_due(recurrence: Recurrence, last_cycle: date | None, today: date) -> date | None:
    """Prochaine échéance, aujourd'hui compris (aujourd'hui aussi pour une occurrence manquée
    depuis le dernier cycle) ; None après la fin de la règle (``UNTIL``)."""
    rule = parse_rule(recurrence.rule)
    if not rule.weekly:
        due = today if last_cycle is None else max(today, last_cycle + timedelta(rule.interval))
    else:
        anchor = recurrence.start or last_cycle or today
        since = last_cycle + timedelta(days=1) if last_cycle is not None else today
        if occurrences(anchor, recurrence.rule, max(since, anchor), today):
            due = today
        else:
            found = occurrences(anchor, recurrence.rule, today, today + timedelta(weeks=53))
            if not found:
                return None
            due = found[0]
    if rule.until is not None and due > rule.until:
        return None
    return due


# --- Graphe ----------------------------------------------------------------------------------


def to_triples(owner: NamedNode, recurrence: Recurrence) -> list[Triple]:
    node = NamedNode(f"{owner.value}/recurrence")
    triples = [
        Triple(owner, vocab("hasRecurrence"), node),
        Triple(node, RDF_TYPE, vocab("Recurrence")),
        Triple(node, vocab("recurrenceRule"), Literal(recurrence.rule)),
    ]
    if recurrence.start is not None:
        triples.append(
            Triple(
                node,
                vocab("recurrenceStart"),
                Literal(recurrence.start.isoformat(), datatype=XSD_DATE),
            )
        )
    return triples


def load(graph: GraphStore, graph_iri: str, owner: str, vocab_ns: str) -> Recurrence | None:
    for row in graph.select(
        f"""
        PREFIX wattslot: <{vocab_ns}>
        SELECT ?rule ?start WHERE {{
          GRAPH <{graph_iri}> {{
            <{owner}> wattslot:hasRecurrence ?node . ?node wattslot:recurrenceRule ?rule .
            OPTIONAL {{ ?node wattslot:recurrenceStart ?start }}
          }}
        }}
        """
    ):
        return Recurrence(
            rule=row["rule"],
            start=date.fromisoformat(row["start"]) if "start" in row else None,
        )
    return None
