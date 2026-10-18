"""Formes SHACL (lot 2b.4) : écrites une fois, elles donnent les mêmes anomalies que le validateur
Python de l'application, sur les profils et sur des configurations fautives (pyshacl, dépendance
de développement seulement)."""

from collections.abc import Callable
from datetime import date
from importlib import resources
from typing import Any

import pytest
import rdflib
from pyshacl import validate

from wattslot import configuration, home_model, profiles
from wattslot.battery_settings import FloorRange
from wattslot.configuration import Automation, Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind
from wattslot.energy_need import EnergyNeed
from wattslot.home_model import HomeDevice, HomeModel
from wattslot.objective_settings import ObjectiveSettings, Preset, Weights
from wattslot.ontology import BASE, VOCAB
from wattslot.recurrence_settings import Recurrence
from wattslot.solar_panels import PanelArray, SolarPanels
from wattslot.tariff import ColorPrices, PriceBand, Tariff, TariffKind
from wattslot.time_constraints import ConstraintKind, TimeConstraint

# Règles écrites en SHACL ; les autres demandent un calcul et restent en Python seulement.
COVERED = {
    "unknown_device",
    "automation_not_available",
    "observed_automation",
    "behavior_not_allowed",
    "runtime_not_used",
    "panels_not_used",
    "need_not_used",
    "constraints_not_used",
    "after_not_used",
    "delay_not_used",
    "recurrence_not_used",
    "after_unknown",
    "need_window_empty",
    "constraint_range_empty",
    "battery_active_range_empty",
    "battery_floor_range_empty",
    "band_empty",
    "tariff_without_bands",
    "tariff_without_colors",
    "tariff_without_color_entity",
    "tariff_without_price_entity",
    "objective_weights_unused",
    "objective_co2_without_entity",
}
ISSUE_CODE = rdflib.URIRef(f"{VOCAB}issueCode")
KEY = rdflib.URIRef(f"{VOCAB}key")
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
EV = profiles.load("ev")
Issues = set[tuple[str, str | None]]


def _turtle(*names: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    folder = resources.files("wattslot.ontology")
    for name in names:
        graph.parse(data=folder.joinpath(name).read_text("utf-8"), format="turtle", publicID=BASE)
    return graph


SHAPES = _turtle("library/home-energy.shapes.ttl", "schema.shapes.ttl")
ONTOLOGY = _turtle("library/home-energy.ttl", "schema.ttl")


def shacl_issues(home: HomeModel, settings: Configuration) -> Issues:
    data = rdflib.Graph()
    triples = home_model.to_triples(home) + configuration.to_triples(settings)
    data.parse(data="\n".join(f"{t} ." for t in triples), format="nt")
    _, results, _ = validate(
        data, shacl_graph=SHAPES, ont_graph=ONTOLOGY, inference="rdfs", allow_warnings=True
    )
    found: Issues = set()
    for result in results.subjects(rdflib.RDF.type, SH.ValidationResult):
        shape = results.value(result, SH.sourceShape)
        code = SHAPES.value(shape, ISSUE_CODE)
        assert code is not None, f"forme sans code d'anomalie : {shape}"
        focus = results.value(result, SH.focusNode)
        found.add((str(code), _device_key(data, focus)))
    return found


def _device_key(data: rdflib.Graph, node: Any) -> str | None:
    """Clé de l'équipement concerné : celle du nœud, ou des réglages qui le portent."""
    key = data.value(node, KEY)
    if key is None:
        owner = next(data.subjects(None, node), None)
        key = data.value(owner, KEY) if owner is not None else None
    return str(key) if key is not None else None


def python_issues(home: HomeModel, settings: Configuration) -> Issues:
    return {(i.code, i.device) for i in configuration.validate(home, settings) if i.code in COVERED}


def changed(key: str, **update: Any) -> Configuration:
    """Configuration du profil « véhicule électrique », un équipement réglé autrement."""
    devices = [d.model_copy(update=update) if d.key == key else d for d in EV.configuration.devices]
    return EV.configuration.model_copy(update={"devices": devices})


def setting(**update: Any) -> Configuration:
    return EV.configuration.model_copy(update=update)


OBSERVED = {"behavior": Behavior.UNCONTROLLED, "automation": Automation.INFORM}
BATTERY = configuration.battery_of(EV.configuration)  # réglée dans le profil

CASES: dict[str, Callable[[], Configuration]] = {
    "comportement non permis": lambda: changed("washing_machine", behavior=Behavior.RUNTIME),
    "pilotage pas encore disponible": lambda: changed("dryer", automation=Automation.CONTROL),
    "observé mais recommandé": lambda: changed("ev", behavior=Behavior.UNCONTROLLED),
    "durée pour un autre comportement": lambda: changed("pool", **OBSERVED),
    "panneaux sur un autre équipement": lambda: changed(
        "pool", panels=SolarPanels(arrays=[PanelArray(kwp=3)]), **OBSERVED
    ),
    "contraintes d'un équipement observé": lambda: changed(
        "dishwasher",
        constraints=[TimeConstraint(kind=ConstraintKind.NOT_BEFORE, start_hour=8)],
        **OBSERVED,
    ),
    "démarre après soi-même": lambda: changed("washing_machine", after="washing_machine"),
    "démarre après un inconnu": lambda: changed("dryer", after="nowhere"),
    "récurrence et report d'un équipement observé": lambda: changed(
        "water_heater",
        max_delay_days=1,
        recurrence=Recurrence(rule="FREQ=DAILY", start=date(2026, 10, 1)),
        **OBSERVED,
    ),
    "fenêtre de besoin vide": lambda: changed(
        "ev", energy=EnergyNeed(energy_kwh=5, earliest_hour=8, deadline_hour=8, max_kw=7.4)
    ),
    "plage interdite vide": lambda: changed(
        "dishwasher",
        constraints=[TimeConstraint(kind=ConstraintKind.FORBIDDEN, start_hour=5, end_hour=5)],
    ),
    "batterie : plages vides": lambda: setting(
        battery=BATTERY.model_copy(
            update={
                "active_from_hour": 10,
                "active_to_hour": 6,
                "floor_ranges": [FloorRange(start_hour=3, end_hour=3, percent=20)],
            }
        )
    ),
    "plages horaires sans plage": lambda: setting(
        tariff=Tariff(kind=TariffKind.TIME_OF_USE, base_eur_kwh=0.2)
    ),
    "plage de prix vide": lambda: setting(
        tariff=Tariff(
            kind=TariffKind.TIME_OF_USE,
            base_eur_kwh=0.2,
            bands=[PriceBand(start_hour=6, end_hour=6, eur_kwh=0.1)],
        )
    ),
    "couleurs sans couleur ni entité": lambda: setting(
        tariff=Tariff(kind=TariffKind.DAY_COLOR, base_eur_kwh=0.2)
    ),
    "couleur sans entité": lambda: setting(
        tariff=Tariff(
            kind=TariffKind.DAY_COLOR,
            base_eur_kwh=0.2,
            colors=[ColorPrices(color="Bleu", base_eur_kwh=0.15)],
        )
    ),
    "prix dynamique sans entité": lambda: setting(
        tariff=Tariff(kind=TariffKind.DYNAMIC, base_eur_kwh=0.2)
    ),
    "poids d'un préréglage": lambda: setting(objective=ObjectiveSettings(weights=Weights())),
    "CO₂ sans entité": lambda: setting(objective=ObjectiveSettings(preset=Preset.CO2)),
    "poids CO₂ sans entité": lambda: setting(
        objective=ObjectiveSettings(preset=Preset.CUSTOM, weights=Weights(cost=1, co2=1))
    ),
    "équipement inconnu": lambda: setting(
        devices=[
            *EV.configuration.devices,
            DeviceSettings(key="ghost", behavior=Behavior.CYCLE),
        ]
    ),
}


@pytest.mark.parametrize("name", profiles.names())
def test_every_profile_conforms(name: str) -> None:
    profile = profiles.load(name)

    assert shacl_issues(profile.home, profile.configuration) == set()
    assert python_issues(profile.home, profile.configuration) == set()


@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
def test_shapes_and_python_find_the_same_issues(case: str) -> None:
    settings = CASES[case]()

    expected = python_issues(EV.home, settings)

    assert expected, "le cas doit être fautif"
    assert shacl_issues(EV.home, settings) == expected


@pytest.mark.parametrize("kind", list(DeviceKind), ids=[k.value for k in DeviceKind])
def test_allowed_behaviors_of_each_kind(kind: DeviceKind) -> None:
    home = HomeModel(devices=[HomeDevice(key="x", kind=kind, name="X", sensors=[])])
    for behavior in Behavior:
        settings = Configuration(
            devices=[DeviceSettings(key="x", behavior=behavior, automation=Automation.INFORM)]
        )

        assert shacl_issues(home, settings) == python_issues(home, settings), behavior


def test_a_malformed_home_breaks_the_library_shapes() -> None:
    home = HomeModel(devices=[HomeDevice(key="x", kind=DeviceKind.SOLAR, name="X", sensors=[])])
    data = rdflib.Graph()
    data.parse(data="\n".join(f"{t} ." for t in home_model.to_triples(home)), format="nt")
    data.remove((None, KEY, None))  # équipement sans clé
    device = next(data.subjects(rdflib.RDF.type, rdflib.URIRef(f"{VOCAB}SolarInstallation")))
    data.remove((device, rdflib.RDF.type, None))
    data.add((device, rdflib.RDF.type, rdflib.URIRef(f"{VOCAB}Toaster")))  # type inconnu

    conforms, results, _ = validate(data, shacl_graph=SHAPES, ont_graph=ONTOLOGY, inference="rdfs")

    assert not conforms
    codes = {
        str(SHAPES.value(results.value(r, SH.sourceShape), ISSUE_CODE))
        for r in results.subjects(rdflib.RDF.type, SH.ValidationResult)
    }
    assert codes == {"device_key", "device_type"}
