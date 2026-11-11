"""Simulation de la batterie en mode autoconsommation, heure par heure.

Réécriture de ``_simuler_soc_batterie`` (v1, ``noeud_calcul.py``), son oracle dans les
tests. La batterie n'est pas pilotée : sur sa plage active, elle charge sur tout le surplus et
se décharge sur tout le déficit, dans la limite de ses puissances, de sa capacité et de son
plancher ; hors plage, elle ne fait rien. Les énergies échangées sont comptées côté maison,
le contenu stocké après pertes (rendement par sens).

Heure en cours (``elapsed``) : le calcul tourne en fin d'heure. Le début de l'heure est ce qui a
été mesuré (``elapsed_change_kwh``), la batterie ne bouge que sur les minutes qui restent. Sans
cela, chaque calcul rejouait l'heure entière depuis le SoC mesuré : une batterie restée au
plancher « se déchargeait » à chaque heure, et le plan additionnait ces décharges.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal


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
    # Batteries qui ne compensent que leur phase : la simulation de chaque groupe, par phase
    # (``residual_kwh`` : échange de la phase après sa batterie). Vide sinon.
    lines: Mapping[Any, "BatteryRun"] = field(default_factory=dict)
    # Avec ``lines`` : la simulation des batteries qui compensent le total, après elles.
    shared: "BatteryRun | None" = None
    # Calcul qui distingue les phases (batteries par phase, ou compteur qui compte chaque
    # phase à part) : échange de chaque phase avec le réseau, par
    # heure (positif injection, négatif soutirage) ; leur somme est ``residual_kwh``. Vide
    # sinon.
    phase_residual_kwh: Mapping[Any, Mapping[int, float]] = field(default_factory=dict)


def _measured(change_kwh: float, charge_efficiency: float, discharge_efficiency: float) -> float:
    """Échange côté maison (positif charge) correspondant à une variation du contenu stocké."""
    if change_kwh > 0:
        return change_kwh / charge_efficiency if charge_efficiency > 0 else 0.0
    return change_kwh * discharge_efficiency


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
    elapsed: float = 0.0,
    elapsed_change_kwh: float = 0.0,
) -> BatteryRun:
    """``net_kwh`` : production moins toute la consommation, par heure (+ surplus) ;
    ``floor_by_hour`` : plancher de certaines heures (plages, lot 3.5), sinon ``floor_kwh`` ;
    ``elapsed`` : part écoulée de ``first_hour``, ``elapsed_change_kwh`` : variation mesurée du
    contenu stocké pendant cette part (``stored_kwh`` : contenu mesuré maintenant)."""
    movements: list[Movement] = []
    soc: dict[int, float] = {}
    residual: dict[int, float] = {}
    stored = stored_kwh
    for hour in range(first_hour, 24):
        net = net_kwh.get(hour, 0.0)
        current = hour == first_hour
        share = 1.0 - elapsed if current else 1.0
        # Échange côté maison : positif charge, négatif décharge ; part mesurée de l'heure en cours.
        exchanged = (
            _measured(elapsed_change_kwh, charge_efficiency, discharge_efficiency)
            if current
            else 0.0
        )
        if active_from <= hour < active_to:
            if net > 0:
                room = (capacity_kwh - stored) / charge_efficiency if charge_efficiency > 0 else 0.0
                taken = max(0.0, min(net * share, charge_max_kw * share, room))
                stored += taken * charge_efficiency
                exchanged += taken
            elif net < 0:
                floor = (floor_by_hour or {}).get(hour, floor_kwh)
                available = max(0.0, stored - floor) * discharge_efficiency
                given = max(0.0, min(-net * share, discharge_max_kw * share, available))
                stored -= given / discharge_efficiency if discharge_efficiency > 0 else 0.0
                exchanged -= given
        if hour in net_kwh:
            residual[hour] = net - exchanged
        if exchanged > 0:
            movements.append(Movement(hour, "charge", round(exchanged, 3)))
        elif exchanged < 0:
            movements.append(Movement(hour, "decharge", round(-exchanged, 3)))
        soc[hour] = stored
    return BatteryRun(movements, stored, soc, residual)
