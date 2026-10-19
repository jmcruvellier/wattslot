// Vues du plan servies par l'API (lot 5.1, backend : views/day.py, views/week.py et leurs
// modules). Seuls les champs lus par l'interface sont décrits.

export type DayKind = "yesterday" | "today" | "tomorrow";
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
  source: "measured" | "plan" | "tonight" | "now";
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
  end_hour: number;
  energy_kwh: number;
  action: "charge" | "discharge" | null;
  mode: string | null;
}

export interface TimelineRow {
  device: string;
  kind: "battery" | "cycle" | "runtime";
  planned: Bar[];
  actual: Bar[];
}

export interface Timeline {
  rows: TimelineRow[];
  empty: "no_surplus" | "nothing" | null;
  production_kwh: number;
  consumption_kwh: number;
  statuses: DeviceStatus[];
  unplanned: Unplanned[];
  badge: "on_time" | "shifted" | null;
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

export interface DeviceExplanation {
  device: string;
  text: string;
}

// Aujourd'hui (lot 6b.3) : puissances moyennes du dernier quart d'heure clos, en watts.
export interface Now {
  since: string | null;
  until: string | null;
  production_w: number | null;
  consumption_w: number | null;
  battery_w: number | null; // positive en charge, négative en décharge
  grid_w: number | null; // positive à l'achat, négative au surplus
  soc_percent: number | null;
  off_peak: boolean;
  sentence: string | null;
}

export interface NextAction {
  device: string;
  start_min: number;
  end_min: number;
  explanation: string | null;
  reminder: boolean;
  can_remind: boolean;
}

export interface DayView {
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
  notices: Notice[];
  freshness: Freshness | null;
  indicators: Indicators | null;
  objective: ObjectivePreset;
  explanations: DeviceExplanation[];
  recommendation: string | null;
  cards: Cards | null;
  now?: Now | null; // Aujourd'hui seulement
  next_action?: NextAction | null;
}

export interface PlannedDevice {
  device: string;
  start_min: number;
  end_min: number;
}

export interface WeekDay {
  day: string;
  detail_view: "today" | "tomorrow" | null;
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
}

export type Versions = Record<ViewKind, number | null>;
