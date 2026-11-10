// Types de l'API « maison » (backend : detection.py, home_model.py).

export const DEVICE_KINDS = [
  "SolarInstallation",
  "GridConnection",
  "Battery",
  "WaterHeater",
  "WashingMachine",
  "Dryer",
  "Dishwasher",
  "PoolPump",
  "OtherLoad",
] as const;
export type DeviceKind = (typeof DEVICE_KINDS)[number];

export type Role =
  | "EnergyProduced"
  | "PowerProduced"
  | "EnergyImported"
  | "EnergyExported"
  | "EnergyCharged"
  | "EnergyDischarged"
  | "StateOfCharge"
  | "EnergyConsumed"
  | "PowerConsumed";

export interface Issue {
  code: string;
  params: Record<string, string>;
}

export interface SensorProposal {
  entity_id: string;
  role: Role;
  name: string | null;
  unit: string | null;
  resets_daily: boolean;
  excluded: boolean;
  issues: Issue[];
}

export interface DeviceProposal {
  key: string;
  kind: DeviceKind;
  name: string;
  sensors: SensorProposal[];
  capacity_kwh: number | null;
  capacity_source?: string | null;
  issues: Issue[];
}

export interface HomeProposal {
  energy_dashboard: boolean;
  devices: DeviceProposal[];
}

export interface HomeSensor {
  entity_id: string;
  role: Role;
  resets_daily: boolean;
  // Réseau en triphasé : le capteur ne mesure que cette phase ; absent ou null : le total.
  phase?: Phase | null;
}

export interface HomeDevice {
  key: string;
  kind: DeviceKind;
  name: string;
  sensors: HomeSensor[];
  capacity_kwh: number | null;
  custom_type?: string | null; // type propre (lot 2t.1), sous-type de kind
  phase?: Phase | null; // branchement en triphasé ; null : inconnu
}

// Alimentation de la maison et branchement d'un équipement (backend : home_model.Supply, Phase).
export type Supply = "SinglePhaseSupply" | "ThreePhaseSupply";
export const PHASES = ["PhaseL1", "PhaseL2", "PhaseL3", "ThreePhases"] as const;
export type Phase = (typeof PHASES)[number];

// Type d'équipement propre à l'installation (backend : home_model.DeviceType).
export interface DeviceType {
  key: string;
  name: string;
  parent: DeviceKind;
}

export interface HomeModel {
  devices: HomeDevice[];
  types?: DeviceType[];
  // Absents d'une requête : le serveur garde ceux qui sont enregistrés.
  supply?: Supply;
  meter_sums_phases?: boolean; // le compteur additionne les trois phases
}

// Capteur de HA qu'on peut lier à un appareil (backend : detection.EntityChoice).
export interface EntityChoice {
  entity_id: string;
  name: string | null;
  unit: string | null;
  roles: Role[];
  resets_daily: boolean;
}

// Type de la bibliothèque (backend : main.LibraryType).
export interface LibraryType {
  kind: DeviceKind;
  behaviors: string[]; // le premier est le comportement par défaut
  roles: Role[];
  subtypes: boolean;
}

export interface DeviceTypes {
  parents: DeviceKind[];
  types: DeviceType[];
  library: LibraryType[];
}
