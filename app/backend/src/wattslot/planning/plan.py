"""Modèle de plan typé (lot 3.1, point n° 1).

Le plan d'une journée : créneaux des équipements, batterie (mouvements, SoC heure par heure),
filtration (segments par mode), avertissements, échange résiduel avec le réseau. Champs en
anglais ; chacun porte en alias sa clé du format de la v1 (JSON de ``calculer_planning``), que
lisent encore la fusion, le dashboard de la v1 et la recommandation : ``Plan.from_v1`` et
``Plan.to_v1`` passent de l'un à l'autre **sans perte** (champs absents laissés absents, clés
inconnues gardées, ordre des éléments conservé).

Les éléments sont encore reconnus au nom réservé de la batterie et de la piscine, comme en v1 ;
les identifiants d'équipements de la configuration les remplaceront (lot 3.4).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

BATTERY = "Batterie"
POOL = "Piscine (filtration)"


def _v1_key(key: str, **kwargs: Any) -> Any:
    """Clé de la v1 d'un champ, lue et écrite ; le constructeur prend le nom anglais."""
    return Field(validation_alias=key, serialization_alias=key, **kwargs)


class _V1(BaseModel):
    """Champs en anglais, clés de la v1 en alias ; clés inconnues gardées."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def to_v1(self) -> dict[str, Any]:
        found: dict[str, Any] = self.model_dump(by_alias=True, exclude_unset=True, mode="python")
        return found


class Reason(_V1):
    """Raison d'une décision (lot 3.7) : un code et ses paramètres, rendus dans la langue voulue
    par ``planning/explain.py``."""

    code: str
    params: dict[str, Any] = {}


class Alternative(_V1):
    """Meilleur autre départ permis d'un cycle, le reste du plan inchangé (batterie rejouée)."""

    start_min: int = _v1_key("debut_min")
    cost_eur_delta: float = _v1_key("ecart_cout_eur")
    import_kwh_delta: float = _v1_key("ecart_soutirage_kwh")


class Explanation(_V1):
    reasons: list[Reason] = _v1_key("raisons", default=[])
    alternative: Alternative | None = None


class Slot(_V1):
    """Créneau d'un équipement : cycle à démarrer, ou cycle déjà lancé recalé sur le réel."""

    device: str = _v1_key("equipement")
    start_hour: int | None = _v1_key("heure_debut", default=None)
    end_hour: int | None = _v1_key("heure_fin", default=None)
    start_min: int | None = _v1_key("debut_min", default=None)
    end_min: int | None = _v1_key("fin_min", default=None)
    energy_kwh: float | None = _v1_key("energie_kwh", default=None)
    cycle_min: int | float | None = _v1_key("duree_cycle_min", default=None)
    shape: list[float] | None = _v1_key("forme_quart_heure", default=None)
    priority: int | None = _v1_key("priorite", default=None)
    justification: str | None = None
    explanation: Explanation | None = _v1_key("explication", default=None)  # lot 3.7
    # Besoin d'énergie (lot 3.4) : énergie fournie à chaque heure, en kWh.
    hourly_kwh: dict[int, float] | None = _v1_key("energie_horaire_kwh", default=None)


class Movement(_V1):
    hour: int = _v1_key("heure")
    action: Literal["charge", "decharge"]
    energy_kwh: float = _v1_key("energie_kwh")


class BatteryPlan(_V1):
    device: str = _v1_key("equipement", default=BATTERY)
    movements: list[Movement] = _v1_key("mouvements", default=[])
    soc_kwh: dict[int, float] = _v1_key("soc_horaire_kwh", default={})  # fin de chaque heure
    charged_kwh: float | None = _v1_key("energie_chargee_kwh", default=None)
    discharged_kwh: float | None = _v1_key("energie_dechargee_kwh", default=None)
    start_kwh: float | None = _v1_key("soc_initial_kwh", default=None)
    end_kwh: float | None = _v1_key("soc_final_kwh", default=None)
    priority: int | None = _v1_key("priorite", default=None)
    justification: str | None = None
    explanation: Explanation | None = _v1_key("explication", default=None)  # lot 3.7

    def to_v1(self) -> dict[str, Any]:
        found = super().to_v1()
        found["equipement"] = self.device  # toujours écrit : il désigne l'élément
        return found


class RuntimeSegment(_V1):
    start_hour: int = _v1_key("heure_debut")
    end_hour: int = _v1_key("heure_fin")
    mode: str  # "off", "silence", "eco"


class RuntimePlan(_V1):
    """Durée de fonctionnement placée : la filtration, par segments d'un même mode."""

    device: str = _v1_key("equipement", default=POOL)
    segments: list[RuntimeSegment] = []
    priority: int | None = _v1_key("priorite", default=None)
    justification: str | None = None
    explanation: Explanation | None = _v1_key("explication", default=None)  # lot 3.7

    def to_v1(self) -> dict[str, Any]:
        found = super().to_v1()
        found["equipement"] = self.device
        return found


def _kind(item: Any) -> str:
    device = item.get("equipement", item.get("device")) if isinstance(item, dict) else None
    if isinstance(item, BatteryPlan) or device == BATTERY:
        return "battery"
    has_segments = isinstance(item, dict) and "segments" in item
    if isinstance(item, RuntimePlan) or device == POOL or has_segments:
        return "runtime"
    return "slot"


Item = Annotated[
    Annotated[Slot, Tag("slot")]
    | Annotated[BatteryPlan, Tag("battery")]
    | Annotated[RuntimePlan, Tag("runtime")],
    Discriminator(_kind),
]


class Indicators(_V1):
    """Indicateurs d'un plan (lot 3.6), sur les heures calculées, batterie simulée : de quoi
    comparer les objectifs."""

    cost_eur: float = _v1_key("cout_eur")  # soutirage au tarif, moins la revente, abonnement
    subscription_eur: float = _v1_key("abonnement_eur", default=0.0)  # part du jour (lot 7.3)
    import_kwh: float = _v1_key("soutirage_kwh")
    export_kwh: float = _v1_key("injection_kwh")
    self_consumption_percent: float | None = _v1_key("autoconsommation_pct", default=None)
    end_soc_percent: float | None = _v1_key("soc_fin_pct", default=None)
    battery_throughput_kwh: float = _v1_key("debit_batterie_kwh", default=0.0)
    co2_kg: float | None = _v1_key("co2_kg", default=None)  # avec une intensité du réseau


class Plan(_V1):
    """Plan d'une journée ; les clés de premier niveau autres que celles-ci (entrée du calcul,
    données réelles, horodatages…) sont gardées telles quelles."""

    day: str | None = _v1_key("date_cible", default=None)  # date ISO
    items: list[Item] = _v1_key("planning", default=[])
    warnings: list[dict[str, Any] | str] = _v1_key("avertissements", default=[])
    residual_kwh: dict[int, float] = _v1_key("residu_reseau_horaire", default={})
    indicators: Indicators | None = _v1_key("indicateurs", default=None)

    @classmethod
    def from_v1(cls, content: dict[str, Any]) -> "Plan":
        return cls.model_validate(content)

    def to_v1(self) -> dict[str, Any]:
        found = super().to_v1()
        if "items" in self.model_fields_set:
            found["planning"] = [item.to_v1() for item in self.items]
        return found

    @property
    def slots(self) -> list[Slot]:
        return [i for i in self.items if isinstance(i, Slot)]

    @property
    def battery(self) -> BatteryPlan | None:
        return next((i for i in self.items if isinstance(i, BatteryPlan)), None)

    @property
    def runtimes(self) -> list[RuntimePlan]:
        return [i for i in self.items if isinstance(i, RuntimePlan)]
