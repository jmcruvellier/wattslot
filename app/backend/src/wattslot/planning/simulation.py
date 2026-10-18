"""Simulation de la batterie en mode autoconsommation, heure par heure.

Réécriture de ``_simuler_soc_batterie`` (v1, ``noeud_calcul.py``), son oracle dans les
tests. La batterie n'est pas pilotée : sur sa plage active, elle charge sur tout le surplus et
se décharge sur tout le déficit, dans la limite de ses puissances, de sa capacité et de son
plancher ; hors plage, elle ne fait rien. Les énergies échangées sont comptées côté maison,
le contenu stocké après pertes (rendement par sens).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Movement:
    hour: int
    action: Literal["charge", "decharge"]
    energy_kwh: float  # arrondi au Wh, comme la v1


@dataclass(frozen=True)
class BatteryRun:
    movements: list[Movement]
    end_kwh: float
    soc_kwh: dict[int, float]  # contenu stocké à la fin de chaque heure simulée
    residual_kwh: dict[int, float]  # échange avec le réseau : positif injection, négatif soutirage


def simulate(
    net_kwh: Mapping[int, float],
    stored_kwh: float,
    capacity_kwh: float,
    charge_max_kw: float,
    discharge_max_kw: float,
    active_from: int,
    active_to: int,
    charge_efficiency: float,
    discharge_efficiency: float,
    floor_kwh: float,
    first_hour: int = 0,
    floor_by_hour: Mapping[int, float] | None = None,
) -> BatteryRun:
    """``net_kwh`` : production moins toute la consommation, par heure (+ surplus) ;
    ``floor_by_hour`` : plancher de certaines heures (plages, lot 3.5), sinon ``floor_kwh``."""
    movements: list[Movement] = []
    soc: dict[int, float] = {}
    residual: dict[int, float] = {}
    stored = stored_kwh
    for hour in range(first_hour, 24):
        net = net_kwh.get(hour, 0.0)
        if hour in net_kwh:
            residual[hour] = net
        if not active_from <= hour < active_to:
            soc[hour] = stored
            continue
        if net > 0:
            room = (capacity_kwh - stored) / charge_efficiency if charge_efficiency > 0 else 0.0
            taken = min(net, charge_max_kw, room)
            if taken > 0:
                stored += taken * charge_efficiency
                residual[hour] = net - taken
                movements.append(Movement(hour, "charge", round(taken, 3)))
        elif net < 0:
            floor = (floor_by_hour or {}).get(hour, floor_kwh)
            available = max(0.0, stored - floor) * discharge_efficiency
            given = min(-net, discharge_max_kw, available)
            if given > 0:
                stored -= given / discharge_efficiency if discharge_efficiency > 0 else 0.0
                residual[hour] = net + given
                movements.append(Movement(hour, "decharge", round(given, 3)))
        soc[hour] = stored
    return BatteryRun(movements, stored, soc, residual)
