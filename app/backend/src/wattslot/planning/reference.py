"""Configuration de référence : les règles de la maison de référence, reprises de la v1.

Ce sont les constantes de ``noeud_calcul.py``, regroupées ici. Elles s'appliquent par
défaut ; leur réglage par l'utilisateur relève du modèle de personnalisation (phase 3). Les
équipements y sont nommés comme dans les tâches de HA, ce qui suffit à la maison de
référence (décision 2 : rien de plus personnel dans le code).
"""

import unicodedata
from dataclasses import dataclass, field


def task_key(text: str) -> str:
    """Clé d'un équipement : minuscules, sans accents ni séparateurs (« Sèche-linge »)."""
    without_accents = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    return without_accents.lower().replace("-", "").replace("_", "").replace(" ", "")


@dataclass(frozen=True)
class Reference:
    # Batterie (plancher, plage active, puissances et charge complète périodique : réglages de la
    # configuration, lot 3.3)
    full_percent: float = 99.5  # « pleine », la simulation plafonnant à la capacité
    # Durées à placer (filtration…) : réglages de chaque équipement, lot 3.4
    # Prévision qui dévie dans la journée : production mesurée inférieure de plus de 10 % à
    # l'estimée, jugée au-delà d'1 kWh estimé
    forecast_drift_percent: float = 10.0
    forecast_drift_min_kwh: float = 1.0
    # Cycles des équipements quand aucun profil de cycle mesuré n'est exploitable
    cycle_hours: dict[str, int] = field(
        default_factory=lambda: {
            task_key("Lave-linge"): 2,
            task_key("Sèche-linge"): 3,
            task_key("Chauffe-eau"): 2,
            task_key("Lave-vaisselle"): 3,
        }
    )
    cycle_min_hours: int = 1
    cycle_max_hours: int = 4
    used_day_fraction: float = 0.3  # jour d'usage réel : au moins 30 % du maximum observé


REFERENCE = Reference()
