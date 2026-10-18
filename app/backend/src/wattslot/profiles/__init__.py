"""Profils de maisons : modèle de la maison et configuration, prêts à charger.

Le profil ``reference`` est la maison de référence (celle de la v1) exprimée dans le modèle de
personnalisation (lot 3.1) : chargé par les tests, il garantit que
la configuration ne change rien aux plans de la v1. Les autres profils de test (lot 3.8 : sans
batterie, sans piscine, Tempo, prix dynamique, véhicule électrique, deux lave-vaisselle,
hémisphère sud) en sont des variantes ; ils serviront de points de départ à l'assistant (phase 4).

Chaque profil est un **fichier d'export** (``exchange``) avec un nom et une description, chargé
par la vérification de l'import. Les entités HA y sont génériques : aucune donnée d'une
installation réelle (décision 2).
"""

import json
from importlib import resources
from typing import Any

from pydantic import BaseModel

from wattslot import exchange
from wattslot.configuration import Configuration
from wattslot.home_model import HomeModel


class Profile(BaseModel):
    name: str
    description: str
    home: HomeModel
    configuration: Configuration


def names() -> list[str]:
    folder = resources.files("wattslot.profiles")
    return sorted(
        p.name.removesuffix(".json") for p in folder.iterdir() if p.name.endswith(".json")
    )


def document(name: str) -> dict[str, Any]:
    """Fichier du profil, tel qu'on l'importe ; ``KeyError`` pour un profil inconnu."""
    if name not in names():
        raise KeyError(name)
    folder = resources.files("wattslot.profiles")
    found: dict[str, Any] = json.loads(folder.joinpath(f"{name}.json").read_text("utf-8"))
    return found


def load(name: str) -> Profile:
    """Profil chargé par la vérification de l'import ; ``ValueError`` s'il n'est pas valide."""
    raw = document(name)
    found, result = exchange.check(raw)
    if found is None:
        raise ValueError(f"profil {name} invalide : {[i.code for i in result.issues]}")
    return Profile(
        name=raw["name"],
        description=raw["description"],
        home=found.home,
        configuration=found.configuration,
    )
