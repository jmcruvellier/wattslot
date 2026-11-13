// Vues du plan servies par l'API (lot 5.1, backend : views/day.py, views/week.py et leurs
// modules). Seuls les champs lus par l'interface sont décrits.

// J+2 à J+6 : jours de l'horizon après demain, affichés comme Demain (prévision seulement).
export type LaterKind = "d2" | "d3" | "d4" | "d5" | "d6";
export type DayKind = "yesterday" | "today" | "tomorrow" | LaterKind;
export type ViewKind = DayKind | "week";

export interface HourPoint {
  hour: number;
  off_peak: boolean;
  production_kwh: number;
  consumption_kwh: number;
  grid_import_kwh: number;
  grid_export_kwh: number;
  battery_charge_kwh: number;
  battery_discharge_kwh: number;
  soc_percent: number | null;
  production_actual_kwh: number | null;
  consumption_actual_kwh: number | null;
  grid_import_actual_kwh: number | null;
  grid_export_actual_kwh: number | null;
  soc_actual_percent: number | null;
}

export interface DaySummary {
  soc_end_kwh: number;
  soc_end_percent: number;
  soc_max_kwh: number;
  soc_max_percent: number;
  soc_max_hour: number;
  charge_kwh: number;
  discharge_kwh: number;
  grid_import_kwh: number;
  grid_export_kwh: number;
  production_kwh: number;
}

export interface Trend {
  direction: "none" | "stable" | "up" | "down" | "infinite";
  percent: number | null;
  favorable: boolean | null;
}

export type LineKey = "soc" | "soc_max" | "charge" | "discharge" | "grid_import" | "grid_export" | "production";

export interface CardLine {
  key: LineKey;
  estimated_kwh: number | null;
  measured_kwh: number | null;
  estimated_hour: number | null;
  measured_hour: number | null;
  measured_percent: number | null;
  trend: Trend;
}

export interface ReadingWeather {
  mode: "reading" | "day" | "day_last" | "no_reading";
  estimated_kwh: number | null;
  measured_kwh: number | null;
  gap_percent: number | null;
  badge: "reliable" | "moderate" | "important" | "too_early" | null;
  initial_at: string | null;
}

export interface Cards {
  reference_hour: number;
  at_reading: CardLine[];
  day: CardLine[] | null;
  weather: ReadingWeather | null;
}

export interface FullCharge {
  days: number | null;
  history_days: number | null;
  priority: boolean;
}

export interface Departure {
  soc_kwh: number;
  soc_percent: number;
  source: "measured" | "plan" | "tonight" | "now" | "eve";
  expected_kwh: number | null;
  expected_percent: number | null;
  expected_at: string | null;
  gap_points: number | null;
  badge: "ok" | "medium" | "large" | "reliable" | "approximate" | null;
  full_charge: FullCharge | null;
}

export interface WeatherBanner {
  production_kwh: number;
  measured: boolean;
  quality: "sunny" | "mixed" | "cloudy" | null;
  share_percent: number | null;
  best_kwh: number | null;
  best_days: number | null;
  today_estimate_kwh: number | null;
  today_gap_percent: number | null;
}

export interface Notice {
  code: string;
  info: boolean;
  text: string;
}

export interface Freshness {
  code: "stale_today" | "stopped_yesterday";
  minutes: number | null;
  last_at: string | null;
}

export interface DeviceStatus {
  device: string;
  status: "on_time" | "shifted" | "no_cycle" | "planned";
  planned_start_min: number;
  planned_end_min: number;
  planned_kwh: number;
  actual_start_min: number | null;
  actual_kwh: number | null;
  running: boolean;
  energy_gap_percent: number | null;
  shift_min: number | null;
}

export interface Unplanned {
  device: string;
  start_min: number;
  energy_kwh: number;
}

export interface Bar {
  start_hour: number;
  end_hour: number; // au-delà de 24 : cycle qui finit le lendemain (débordement après minuit)
  energy_kwh: number;
  action: "charge" | "discharge" | null;
  mode: string | null;
  carried?: boolean; // fin d'un cycle commencé la veille avant minuit : rien à lancer
  // Barre prévue d'un cycle : son identité, le nom de l'équipement ou, à partir de son deuxième
  // cycle de la journée, ce nom et son rang (« Lave-linge #2 ») ; c'est elle que prennent le
  // départ choisi et « Annuler ».
  cycle?: string | null;
}

export interface TimelineRow {
  device: string;
  kind: "battery" | "cycle" | "runtime";
  planned: Bar[];
  actual: Bar[];
  // Batteries d'une même phase (calcul par phase) : 1, 2 ou 3 ; 0 : celles qui compensent le
  // total ; absent ou null : la batterie de la maison, ou un autre équipement.
  phase?: number | null;
}

export interface Timeline {
  rows: TimelineRow[];
  empty: "no_surplus" | "nothing" | null;
  production_kwh: number;
  consumption_kwh: number;
  statuses: DeviceStatus[];
  unplanned: Unplanned[];
  badge: "on_time" | "shifted" | null;
  cancelled?: string[]; // planifications annulées pour aujourd'hui (vue Aujourd'hui seule)
}

export type ObjectivePreset = "cost" | "autonomy" | "self_consumption" | "co2" | "custom";

export interface Indicators {
  cost_eur: number; // abonnement compris
  subscription_eur?: number; // part de l'abonnement du jour (lot 7.3)
  import_kwh: number;
  export_kwh: number;
  self_consumption_percent: number | null;
  end_soc_percent: number | null;
  battery_throughput_kwh: number;
  co2_kg: number | null;
}

// Autre départ d'un cycle (clés de la v1 gardées par le plan typé).
export interface PlanAlternative {
  debut_min: number;
  ecart_cout_eur: number;
  ecart_soutirage_kwh: number;
}

export interface DeviceExplanation {
  device: string;
  text: string;
  // Explication structurée : autres départs proposés, départ choisi par l'utilisateur.
  explanation?: { alternatives?: PlanAlternative[]; choisi?: boolean };
}

// Aujourd'hui (lot 6b.3) : puissances moyennes du dernier quart d'heure clos, en watts.
// Une batterie de la maison, à son dernier relevé (backend : views.now.BatteryNow).
export interface BatteryNow {
  key: string;
  name: string;
  capacity_kwh: number | null;
  phase?: string | null; // maison en triphasé : PhaseL1, PhaseL2, PhaseL3 ou ThreePhases
  soc_percent: number | null;
  stored_kwh: number | null;
  power_w: number | null; // positive en charge, négative en décharge
}

// Plan demandé phase par phase mais calculé sur le total (backend : views.now.PhaseGap).
export interface PhaseGap {
  code: "meters" | "devices" | "history";
  params: Record<string, string>;
}

export interface Now {
  since: string | null;
  until: string | null;
  production_w: number | null;
  consumption_w: number | null;
  battery_w: number | null; // positive en charge, négative en décharge
  grid_w: number | null; // positive à l'achat, négative au surplus
  soc_percent: number | null; // plusieurs batteries : leur moyenne pondérée par la capacité
  batteries?: BatteryNow[]; // chaque batterie de la maison
  phase_gap?: PhaseGap | null; // ce qui empêche le plan d'être calculé phase par phase
  off_peak: boolean;
  sentence: string | null;
}

export interface NextAction {
  device: string;
  start_min: number;
  end_min: number;
  explanation: string | null;
  late?: boolean; // heure de départ prévue dépassée, cycle pas encore vu
  reminder: boolean;
  can_remind: boolean;
  // Autres départs à venir, proposés par le plan, et départ choisi par l'utilisateur.
  alternatives?: { start_min: number; end_min: number; cost_eur_delta: number; import_kwh_delta: number }[];
  chosen?: boolean;
}

// Échanges d'une phase avec le réseau sur la journée (backend : views.day.PhaseDay).
export interface PhaseDay {
  phase: number; // 1, 2 ou 3
  import_kwh: number;
  export_kwh: number;
  import_actual_kwh?: number | null; // mesuré jusqu'ici par les capteurs de la phase
  export_actual_kwh?: number | null;
}

export interface DayView {
  phases?: PhaseDay[]; // triphasé, plan calculé par phase
  kind: DayKind;
  day: string;
  computed_at: string | null;
  manual: boolean;
  actual_updated_at: string | null;
  battery_capacity_kwh: number | null;
  battery_floor_percent: number | null;
  hours: HourPoint[];
  summary: DaySummary;
  initial_forecast: DaySummary | null;
  timeline: Timeline;
  departure: Departure | null;
  weather: WeatherBanner;
  // Faux : maison sans installation solaire (lot 7.4), ni carte Soleil ni bandeau météo.
  solar?: boolean;
  // Plan calculé pendant la reprise de l'historique de HA : compteurs restants (plan provisoire).
  history_pending?: number | null;
  // Heures dont une mesure impossible a été écartée (qualité des données).
  discarded_hours?: number[];
  notices: Notice[];
  freshness: Freshness | null;
  indicators: Indicators | null;
  // Qualité des prévisions d'après les données du calcul ; absente : plan d'avant ce critère.
  forecast_quality?: ForecastQuality | null;
  objective: ObjectivePreset;
  explanations: DeviceExplanation[];
  recommendation: string | null;
  cards: Cards | null;
  now?: Now | null; // Aujourd'hui seulement
  next_action?: NextAction | null;
  // Sans prochaine action : pourquoi (tout est lancé, annulé, rien de prévu aujourd'hui).
  idle_reason?: "all_started" | "cancelled" | "nothing_planned" | null;
  declared_launches?: string[]; // « C'est lancé » sur lequel on peut encore revenir
}

export type QualityLevel = "good" | "fair" | "poor";

export type QualityCode =
  | "consumption_history"
  | "consumption_regularity"
  | "solar_source"
  | "weather_horizon"
  | "cycle_profiles"
  | "history_import";

export interface QualityFactor {
  code: QualityCode;
  level: QualityLevel;
  params: Record<string, string | number | boolean>;
}

export interface ForecastQuality {
  level: QualityLevel;
  score: number; // 0 à 100
  factors: QualityFactor[]; // les plus faibles d'abord
}

export interface PlannedDevice {
  device: string;
  start_min: number;
  end_min: number;
}

export interface WeekDay {
  day: string;
  detail_view: "today" | "tomorrow" | LaterKind | null;
  production_kwh: number;
  weather: "sunny" | "mixed" | "cloudy" | null;
  soc_start_percent: number | null;
  soc_end_percent: number | null;
  soc_max_percent: number | null;
  grid_import_kwh: number;
  grid_import_peak_kwh: number;
  grid_export_kwh: number;
  devices: PlannedDevice[];
  notices: Notice[];
}

export interface WeekPoint {
  day: string;
  hour: number;
  off_peak: boolean;
  soc_percent: number | null;
  soc_kwh: number | null;
  production_kwh: number;
  consumption_kwh: number;
}

export interface WeekView {
  computed_at: string | null;
  manual: boolean;
  seconds: number | null;
  days: WeekDay[];
  points: WeekPoint[];
  floor_percent: number;
  now_index: number | null;
  notices: Notice[];
  waiting_not_assigned: boolean;
  missing_days: string[]; // jours de l'horizon que le calcul n'a pas atteints (cause dans notices)
  // Heures du premier jour (aujourd'hui) dont une mesure impossible a été écartée ; rien si la
  // mesure est plus ancienne que la semaine affichée.
  discarded_hours?: number[];
  solar?: boolean; // faux : maison sans panneaux, ni météo ni production
}

export type Versions = Record<ViewKind, number | null>;
