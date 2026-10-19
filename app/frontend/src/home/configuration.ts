// Types de l'API de configuration (backend : configuration.py) et règles qu'elle applique.

import type { DeviceKind, Issue } from "./types";

export type Behavior =
  | "CycleBehavior"
  | "EnergyByDeadlineBehavior"
  | "RuntimeBehavior"
  | "StorageBehavior"
  | "UncontrolledBehavior"
  | "ProductionBehavior"
  | "GridBehavior";

export type Automation = "InformAutomation" | "RecommendAutomation" | "ConfirmAutomation" | "ControlAutomation";

export interface Speed {
  name: string; // mode dans le plan
  kw: number;
}

export const SEASONS = ["summer", "mid_season", "winter"] as const;

export interface RuntimeSettings {
  speeds: Speed[]; // vide : une vitesse, mesurée sur l'historique
  minimum_hours: Record<string, number>; // par saison
  skip_days: Record<string, number>;
  max_starts: number;
}

// Réglages par défaut (backend : runtime_settings.DEFAULT).
export const DEFAULT_RUNTIME: RuntimeSettings = {
  speeds: [],
  minimum_hours: { summer: 2, mid_season: 1, winter: 0 },
  skip_days: { summer: 1, mid_season: 2, winter: 365 },
  max_starts: 2,
};

// Besoin d'énergie avant une échéance (backend : energy_need.EnergyNeed).
export interface EnergyNeed {
  energy_kwh: number;
  earliest_hour: number;
  deadline_hour: number; // énergie fournie avant cette heure
  max_kw: number;
  steps: boolean; // tout ou rien à la puissance maximale
  daily: boolean; // sinon les jours où une tâche de HA le demande
}

// Point de départ de l'éditeur (pas un réglage du backend : sans besoin réglé, cycle à démarrer).
export const DEFAULT_ENERGY_NEED: EnergyNeed = {
  energy_kwh: 5,
  earliest_hour: 0,
  deadline_hour: 7,
  max_kw: 2,
  steps: false,
  daily: true,
};

// Contrainte horaire (backend : time_constraints.TimeConstraint).
export const CONSTRAINT_KINDS = ["forbidden", "not_before", "finish_before"] as const;
export type ConstraintKind = (typeof CONSTRAINT_KINDS)[number];

export interface TimeConstraint {
  kind: ConstraintKind;
  start_hour: number; // plage interdite (début), pas avant
  end_hour: number; // plage interdite (fin, exclue), terminé avant
  hard: boolean; // sinon souple : violée au besoin, signalée
}

// Comportements placés par le calcul, qui acceptent des contraintes horaires.
export const CONSTRAINED: Behavior[] = ["CycleBehavior", "EnergyByDeadlineBehavior", "RuntimeBehavior"];

// Récurrence d'un cycle (backend : recurrence_settings.Recurrence), règle RFC 5545.
export interface Recurrence {
  rule: string;
  start?: string | null; // date ISO : semaine de départ d'un intervalle hebdomadaire
}

// Règles reprises des descriptions JSON des tâches de HA (backend : assemble.TaskRules).
export interface TaskRules {
  key: string;
  recurrence: Recurrence | null;
  after: string | null;
}

// Panneaux d'une installation solaire (lot 4.4, backend : solar_panels.py).
export interface PanelArray {
  kwp: number; // puissance crête
  tilt: number; // inclinaison (°), 0 à plat
  azimuth: number; // orientation (°, boussole) : 180 plein sud
}

export interface SolarPanels {
  arrays: PanelArray[];
  inverter_kw: number | null; // plafond de l'onduleur ; null : aucun
  efficiency: number; // rendement global hors température (0,9 par défaut)
}

export interface DeviceSettings {
  key: string;
  behavior: Behavior;
  automation: Automation;
  planned: boolean;
  default: boolean;
  runtime?: RuntimeSettings | null; // durée de fonctionnement à placer ; null : défaut
  panels?: SolarPanels | null; // installation solaire : panneaux pour la prévision Open-Meteo (lot 4.4)
  energy?: EnergyNeed | null; // besoin d'énergie ; null : traité comme un cycle à démarrer
  constraints?: TimeConstraint[]; // contraintes horaires (lot 3.5)
  after?: string | null; // cycle : après la fin du cycle de cet équipement (clé), lot 3.5
  max_delay_days?: number | null; // cycle : tolérance de report ; null : 2 jours
  recurrence?: Recurrence | null; // cycle : récurrence (lot 3.5) ; null : tâches de HA
}

export interface PriceBand {
  start_hour: number;
  end_hour: number; // exclue
  eur_kwh: number;
  weekdays: number[]; // 0 lundi … 6 dimanche ; vide : tous les jours
  months: number[]; // 1 … 12 ; vide : toute l'année
}

export type TariffKind = "SingleTariff" | "TimeOfUseTariff" | "DayColorTariff" | "DynamicTariff";
export const TARIFF_KINDS: TariffKind[] = ["SingleTariff", "TimeOfUseTariff", "DayColorTariff", "DynamicTariff"];

export interface ColorPrices {
  color: string; // état de l'entité de couleur (casse, accents et anglais ignorés)
  base_eur_kwh: number;
  bands: PriceBand[];
}

export interface Tariff {
  kind: TariffKind;
  base_eur_kwh: number; // prix unique, hors des plages, ou prix inconnu
  bands: PriceBand[];
  export_eur_kwh: number;
  colors: ColorPrices[]; // la première : couleur d'un jour inconnu
  color_entity: string | null;
  color_tomorrow_entity: string | null;
  color_day_start_hour: number;
  price_entity: string | null;
  export_entity: string | null;
  price_factor: number; // unité des entités vers €/kWh
  subscription_eur_month: number; // abonnement, ajouté au coût de chaque jour au prorata du mois
  contract_kva: number | null; // puissance souscrite ; null : inconnue
}

export interface BatterySettings {
  charge_max_w: number | null; // null : 0,5 C
  discharge_max_w: number | null;
  floor_percent: number;
  active_from_hour: number;
  active_to_hour: number; // exclue
  full_charge_every_days: number | null; // null : jamais
  floor_ranges?: FloorRange[]; // plancher plus haut sur ces plages (lot 3.5)
}

export interface FloorRange {
  start_hour: number;
  end_hour: number; // exclue ; à cheval sur minuit si start_hour > end_hour
  percent: number;
}

// Réglages par défaut (backend : battery_settings.DEFAULT) et puissance par défaut (0,5 C).
export const DEFAULT_BATTERY: BatterySettings = {
  charge_max_w: null,
  discharge_max_w: null,
  floor_percent: 10,
  active_from_hour: 0,
  active_to_hour: 24,
  full_charge_every_days: 7,
};
export const C_RATE = 0.5;

// Objectif du calcul (backend : objective_settings) ; poids en équivalent euros.
export const PRESETS = ["cost", "autonomy", "self_consumption", "co2", "custom"] as const;
export type Preset = (typeof PRESETS)[number];

export interface Weights {
  cost: number;
  grid_import: number;
  grid_export: number;
  co2?: number; // kWh soutirés pondérés par l'intensité carbone de l'heure
  battery?: number; // kWh passés par la batterie (ménagement)
}

export interface ObjectiveSettings {
  preset: Preset;
  weights: Weights | null; // poids libres (custom) ; sinon ceux du préréglage
  co2_entity?: string | null; // intensité carbone du réseau (g/kWh), entité de HA
}

export interface Configuration {
  version: number;
  devices: DeviceSettings[];
  tariff: Tariff | null; // null : prix unique par défaut (backend : tariff.DEFAULT)
  battery?: BatterySettings | null; // null : réglages par défaut (backend : battery_settings)
  objective?: ObjectiveSettings | null; // null : réglage du calcul (coût par défaut), lot 3.6
}

export const DEFAULT_PRICE_EUR_KWH = 0.25;

const band = (start_hour: number, end_hour: number, eur_kwh: number): PriceBand => ({
  start_hour,
  end_hour,
  eur_kwh,
  weekdays: [],
  months: [],
});
const offPeak = (eur_kwh: number) => [band(0, 6, eur_kwh), band(22, 24, eur_kwh)];

const BLANK: Omit<Tariff, "kind" | "base_eur_kwh"> = {
  bands: [],
  export_eur_kwh: 0,
  colors: [],
  color_entity: null,
  color_tomorrow_entity: null,
  color_day_start_hour: 0,
  price_entity: null,
  export_entity: null,
  price_factor: 1,
  subscription_eur_month: 0,
  contract_kva: null,
};

// Modèles de départ du formulaire (prix et entités à remplacer par ceux de l'installation).
export const TARIFF_TEMPLATES: Record<TariffKind, Tariff> = {
  SingleTariff: { ...BLANK, kind: "SingleTariff", base_eur_kwh: DEFAULT_PRICE_EUR_KWH },
  TimeOfUseTariff: { ...BLANK, kind: "TimeOfUseTariff", base_eur_kwh: 0.2, bands: offPeak(0.15) },
  DayColorTariff: {
    ...BLANK,
    kind: "DayColorTariff",
    base_eur_kwh: 0.2,
    color_day_start_hour: 6, // Tempo : la couleur vaut de 6 h à 6 h le lendemain
    colors: [
      { color: "Bleu", base_eur_kwh: 0.16, bands: offPeak(0.13) },
      { color: "Blanc", base_eur_kwh: 0.19, bands: offPeak(0.15) },
      { color: "Rouge", base_eur_kwh: 0.75, bands: offPeak(0.16) },
    ],
  },
  DynamicTariff: { ...BLANK, kind: "DynamicTariff", base_eur_kwh: DEFAULT_PRICE_EUR_KWH },
};

// Unités possibles des entités de prix (facteur vers €/kWh).
export const PRICE_UNITS: { factor: number; unit: string }[] = [
  { factor: 1, unit: "€/kWh" },
  { factor: 0.01, unit: "c€/kWh" },
  { factor: 0.001, unit: "€/MWh" },
];

export interface ConfigurationIssue extends Issue {
  device: string | null;
}

// Comportements possibles par type d'équipement, le premier par défaut (BEHAVIORS du backend).
export const BEHAVIORS: Record<DeviceKind, Behavior[]> = {
  SolarInstallation: ["ProductionBehavior"],
  GridConnection: ["GridBehavior"],
  Battery: ["StorageBehavior"],
  WaterHeater: ["CycleBehavior", "EnergyByDeadlineBehavior", "UncontrolledBehavior"],
  WashingMachine: ["CycleBehavior", "UncontrolledBehavior"],
  Dryer: ["CycleBehavior", "UncontrolledBehavior"],
  Dishwasher: ["CycleBehavior", "UncontrolledBehavior"],
  PoolPump: ["RuntimeBehavior", "UncontrolledBehavior"],
  OtherLoad: ["UncontrolledBehavior", "CycleBehavior", "EnergyByDeadlineBehavior", "RuntimeBehavior"],
};

// Équipements seulement observés : ni automatisation, ni prise en compte par le calcul à régler.
const OBSERVED: Behavior[] = ["ProductionBehavior", "GridBehavior", "UncontrolledBehavior"];

export function isObserved(behavior: Behavior): boolean {
  return OBSERVED.includes(behavior);
}

// Le pilotage vient après la première publication : information pour un équipement observé,
// recommandation sinon.
export function automationFor(behavior: Behavior): Automation {
  return isObserved(behavior) ? "InformAutomation" : "RecommendAutomation";
}
