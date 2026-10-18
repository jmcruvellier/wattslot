"""Journées types et résultats figés de la v1, oracles des tests différentiels (lot 2.1).

La v2 est une réécriture d'une première version propre à une maison (la v1) : chaque module
réécrit devait donner les mêmes résultats que la v1 sur les mêmes entrées. Ces résultats ont été
calculés une fois avec le vrai code de la v1 et figés dans ``fixtures/v1/`` ; les tests
comparent la v2 à ces fichiers, avec les mêmes tolérances qu'à l'origine.

- ``STATES`` : 13 journées types (``fixtures/days/``), chacune l'entrée du calcul de la v1 et sa
  sortie. Elles viennent de journées réelles anonymisées : dates décalées, valeurs de production
  et de consommation bruitées, identifiants génériques.
- ``v1(name, *args)`` : résultat figé de la fonction ``name`` de la v1 sur ces entrées (repéré par
  le nom et une empreinte des entrées). Des entrées sans résultat figé font échouer le test :
  les résultats ne se régénèrent qu'avec le code de la v1, qui ne fait pas partie de ce dépôt.
  Un test qui change ses entrées vers la v1 garde donc les anciennes, ou devient un test propre
  à la v2.
"""

import copy
import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any

FORMAT = 1
FIXTURES = Path(__file__).resolve().parent / "fixtures"
STATES = sorted((FIXTURES / "days").glob("*.json"))
REFERENCES = FIXTURES / "v1"
RAISES = "__raises__"


class V1Raised(Exception):
    """La v1 a levé une exception de ce nom sur ces entrées."""


# Calcul par la v1, posé seulement pendant l'enregistrement des résultats figés (outil hors de
# ce dépôt) : appelé avec le nom et des copies des entrées ; lève ``V1Raised`` quand la v1 lève.
recorder: Callable[[str, tuple[Any, ...], dict[str, Any]], Any] | None = None
recorded: dict[str, dict[str, Any]] = {}  # fichier → empreinte → résultat encodé


def encode(value: Any) -> Any:
    """Valeur Python → JSON étiqueté : dates, tuples, ensembles et clés non textuelles gardent
    leur type à la relecture (format des captures de la v1)."""
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, dict):
        if all(isinstance(k, str) and not k.startswith("__") for k in value):
            return {k: encode(v) for k, v in value.items()}
        return {"__dict__": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, tuple):
        return {"__tuple__": [encode(v) for v in value]}
    if isinstance(value, set | frozenset):
        return {"__set__": sorted((encode(v) for v in value), key=repr)}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Type non représentable : {type(value).__name__}")


def decode(value: Any) -> Any:
    """Inverse de ``encode``."""
    if isinstance(value, list):
        return [decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        ((tag, content),) = value.items()
        if tag == "__datetime__":
            return datetime.fromisoformat(content)
        if tag == "__date__":
            return date.fromisoformat(content)
        if tag == "__dict__":
            return {_hashable(decode(k)): decode(v) for k, v in content}
        if tag == "__tuple__":
            return tuple(decode(v) for v in content)
        if tag == "__set__":
            return {_hashable(decode(v)) for v in content}
    return {k: decode(v) for k, v in value.items()}


def _hashable(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


@cache
def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(entrée, sortie de la v1) d'une journée type ; des objets neufs à chaque appel."""
    content = _read(path)
    if content.get("format") != FORMAT:
        raise ValueError(f"{path.name} : format {content.get('format')!r} inconnu")
    return decode(content["entree"]), decode(content["sortie"])


def state_named(stem: str) -> Path:
    """Journée type dont le nom contient ``stem`` (« tomorrow_laundry »…)."""
    (found,) = [p for p in STATES if stem in p.stem]
    return found


def _stable(value: Any) -> Any:
    """Flottants à 12 chiffres significatifs : l'empreinte ne dépend pas du dernier bit (somme des
    flottants de Python 3.12, bibliothèque mathématique de la plateforme)."""
    if isinstance(value, float):
        return float(f"{value:.12g}")
    if isinstance(value, list):
        return [_stable(v) for v in value]
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items()}
    return value


def fingerprint(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    stable = _stable(encode([list(args), kwargs]))
    payload = json.dumps(stable, ensure_ascii=False, separators=(",", ":"))
    return f"{name}:{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def group(name: str) -> str:
    return name.split(".", 1)[0]


def v1(name: str, *args: Any, **kwargs: Any) -> Any:
    """Résultat figé de ``name`` (« module.fonction », ou une constante) sur ces entrées."""
    key = fingerprint(name, args, kwargs)
    if recorder is not None:
        try:
            value = encode(recorder(name, copy.deepcopy(args), copy.deepcopy(kwargs)))
        except V1Raised as raised:
            value = {RAISES: str(raised)}
        recorded.setdefault(group(name), {})[key] = value
    else:
        path = REFERENCES / f"{group(name)}.json"
        references = _read(path) if path.is_file() else {}
        if key not in references:
            raise LookupError(
                f"{name} : pas de résultat figé de la v1 pour ces entrées ({key}). Les entrées "
                "du test ont changé : les résultats figés ne se régénèrent qu'avec la v1."
            )
        value = references[key]
    if isinstance(value, dict) and set(value) == {RAISES}:
        raise V1Raised(value[RAISES])
    return decode(value)
