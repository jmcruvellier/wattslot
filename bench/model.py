"""Maison synthétique du banc : environ 160 entités, comme la maison de référence.

Modèle RDF repris de la v1 (SOSA) : chaque capteur est hébergé par une plateforme
(``sosa:isHostedBy``) et observe une propriété. Le modèle vit dans son propre graphe nommé
(décision 12 : la description de la maison est dans l'ontologie).
"""

from dataclasses import dataclass
from enum import StrEnum

VOCAB = "urn:wattslot:"
SOSA = "http://www.w3.org/ns/sosa/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

GRAPH_HOME = f"{VOCAB}graph:home"


class Kind(StrEnum):
    POWER = "power"  # puissance instantanée (W), change souvent
    ENERGY = "energy"  # compteur d'énergie cumulé (kWh)
    MEASUREMENT = "measurement"  # autre mesure lente (température, état de charge, tension…)


@dataclass(frozen=True)
class Sensor:
    index: int
    kind: Kind
    platform: str
    role: str  # rôle pour les requêtes : solar, home, grid_import, battery_charge, appliance…

    @property
    def iri(self) -> str:
        return f"{VOCAB}sensor/{self.index}"

    @property
    def property_iri(self) -> str:
        return f"{VOCAB}property/{self.kind}"

    @property
    def class_iri(self) -> str:
        return f"{VOCAB}class/{self.kind.capitalize()}Sensor"


APPLIANCES = ("water_heater", "washing_machine", "dryer", "dishwasher")


def build_home(power: int = 40, energy: int = 60, measurement: int = 60) -> list[Sensor]:
    """Capteurs de la maison ; les premiers de chaque sorte ont un rôle utilisé par les requêtes."""
    roles = {
        Kind.POWER: ["solar", "home", "grid", "battery", *APPLIANCES],
        Kind.ENERGY: [
            "solar",
            "home",
            "grid_import",
            "grid_export",
            "battery_charge",
            "battery_discharge",
            *APPLIANCES,
        ],
        Kind.MEASUREMENT: ["battery_soc"],
    }
    sensors: list[Sensor] = []
    for kind, count in (
        (Kind.POWER, power),
        (Kind.ENERGY, energy),
        (Kind.MEASUREMENT, measurement),
    ):
        for i in range(count):
            role = roles[kind][i] if i < len(roles[kind]) else "other"
            platform = role if role in APPLIANCES else f"platform_{i % 12}"
            sensors.append(Sensor(len(sensors), kind, f"{VOCAB}platform/{platform}", role))
    return sensors


def home_nquads(sensors: list[Sensor]) -> str:
    graph = f"<{GRAPH_HOME}>"
    lines = []
    for s in sensors:
        lines.append(f"<{s.iri}> <{RDF_TYPE}> <{s.class_iri}> {graph} .")
        lines.append(f"<{s.iri}> <{SOSA}isHostedBy> <{s.platform}> {graph} .")
        lines.append(f"<{s.iri}> <{SOSA}observes> <{s.property_iri}> {graph} .")
        lines.append(f'<{s.iri}> <{VOCAB}role> "{s.role}" {graph} .')
        if s.role in APPLIANCES:
            lines.append(f"<{s.platform}> <{RDF_TYPE}> <{VOCAB}class/Appliance> {graph} .")
    return "\n".join(lines) + "\n"
