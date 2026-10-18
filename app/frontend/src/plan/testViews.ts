// Vues complètes pour les tests de l'écran du plan (lot 5.3).

import type { CardLine, DayView, HourPoint, WeekDay, WeekPoint, WeekView } from "./types";

export const HOURS: HourPoint[] = Array.from({ length: 24 }, (_, hour) => ({
  hour,
  off_peak: hour < 6 || hour >= 22,
  production_kwh: hour >= 8 && hour < 18 ? 1 : 0,
  consumption_kwh: 0.4,
  grid_import_kwh: hour < 8 ? 0.4 : 0,
  grid_export_kwh: hour === 13 ? 0.2 : 0,
  battery_charge_kwh: hour >= 9 && hour < 13 ? 0.5 : 0,
  battery_discharge_kwh: hour >= 18 ? 0.3 : 0,
  soc_percent: 50,
  production_actual_kwh: hour < 14 ? 1 : null,
  consumption_actual_kwh: hour < 14 ? 0.5 : null,
  grid_import_actual_kwh: null,
  grid_export_actual_kwh: null,
  soc_actual_percent: null,
}));

const line = (key: CardLine["key"], estimated: number, measured: number, trend: CardLine["trend"]): CardLine => ({
  key,
  estimated_kwh: estimated,
  measured_kwh: measured,
  estimated_hour: key === "soc_max" ? 14.5 : null,
  measured_hour: key === "soc_max" ? 0 : null,
  measured_percent: key === "soc" || key === "soc_max" ? 60 : null,
  trend,
});

const UP = { direction: "up", percent: 25, favorable: true } as const;
const STABLE = { direction: "stable", percent: 0, favorable: null } as const;

export const TODAY: DayView = {
  kind: "today",
  day: "2026-10-17",
  computed_at: "2026-10-17T13:59:00",
  manual: false,
  actual_updated_at: "2026-10-17T14:30:00",
  battery_capacity_kwh: 5.12,
  battery_floor_percent: 12,
  hours: HOURS,
  summary: {
    soc_end_kwh: 2,
    soc_end_percent: 40,
    soc_max_kwh: 5,
    soc_max_percent: 98,
    soc_max_hour: 16,
    charge_kwh: 3,
    discharge_kwh: 2,
    grid_import_kwh: 1,
    grid_export_kwh: 0.5,
    production_kwh: 10,
  },
  initial_forecast: null,
  timeline: {
    rows: [
      {
        device: "Batterie",
        kind: "battery",
        planned: [{ start_hour: 9, end_hour: 13, energy_kwh: 2, action: "charge", mode: null }],
        actual: [{ start_hour: 9.25, end_hour: 13.5, energy_kwh: 2.1, action: "charge", mode: null }],
      },
      {
        device: "Lave-linge",
        kind: "cycle",
        planned: [{ start_hour: 10, end_hour: 11.5, energy_kwh: 1, action: null, mode: null }],
        actual: [{ start_hour: 10.0833, end_hour: 11.5, energy_kwh: 1.3, action: null, mode: null }],
      },
      {
        device: "Piscine",
        kind: "runtime",
        planned: [{ start_hour: 11, end_hour: 15, energy_kwh: 1.66, action: null, mode: "eco" }],
        actual: [],
      },
    ],
    empty: null,
    production_kwh: 10,
    consumption_kwh: 9.6,
    statuses: [
      {
        device: "Lave-linge",
        status: "on_time",
        planned_start_min: 600,
        planned_end_min: 690,
        planned_kwh: 1,
        actual_start_min: 605,
        actual_kwh: 1.3,
        running: false,
        energy_gap_percent: 30,
        shift_min: null,
      },
      {
        device: "Chauffe-eau",
        status: "planned",
        planned_start_min: 900,
        planned_end_min: 1020,
        planned_kwh: 2,
        actual_start_min: null,
        actual_kwh: null,
        running: false,
        energy_gap_percent: null,
        shift_min: null,
      },
    ],
    unplanned: [],
    badge: "on_time",
  },
  departure: {
    soc_kwh: 2.56,
    soc_percent: 50,
    source: "measured",
    expected_kwh: 2.5,
    expected_percent: 48.8,
    expected_at: "2026-10-16T17:59:00",
    gap_points: 1,
    badge: "ok",
    full_charge: { days: 2, history_days: null, priority: false },
  },
  weather: {
    production_kwh: 9.5,
    measured: false,
    quality: "sunny",
    share_percent: 80,
    best_kwh: 12,
    best_days: 30,
    today_estimate_kwh: null,
    today_gap_percent: null,
  },
  notices: [{ code: "tache_reportee", info: true, text: "Sèche-linge reporté au dimanche 18 octobre." }],
  freshness: null,
  indicators: {
    cost_eur: 1.23,
    import_kwh: 4.5,
    export_kwh: 0.7,
    self_consumption_percent: 92,
    end_soc_percent: 40,
    battery_throughput_kwh: 5,
    co2_kg: null,
  },
  objective: "autonomy",
  explanations: [{ device: "Lave-linge", text: "Placé à 10h pour profiter du soleil." }],
  recommendation: "Lave-linge : 10h00\nChauffe-eau : 15h00",
  cards: {
    reference_hour: 14.5,
    at_reading: [
      line("soc", 2.4, 3.0, UP),
      line("soc_max", 4.0, 5.0, UP),
      line("charge", 2.0, 2.0, STABLE),
      line("discharge", 0.5, 0.5, STABLE),
      line("grid_import", 1.0, 1.25, { direction: "up", percent: 25, favorable: false }),
      line("grid_export", 0, 0.1, { direction: "infinite", percent: null, favorable: false }),
      line("production", 6.0, 6.5, { direction: "up", percent: 8, favorable: true }),
    ],
    day: [line("soc", 2.0, 2.2, UP), line("production", 9.0, 9.5, UP)],
    weather: {
      mode: "reading",
      estimated_kwh: 6,
      measured_kwh: 6.5,
      gap_percent: 8,
      badge: "reliable",
      initial_at: null,
    },
  },
};

export const YESTERDAY: DayView = {
  ...TODAY,
  kind: "yesterday",
  day: "2026-10-16",
  cards: { ...TODAY.cards!, reference_hour: 24, day: null },
};

export const TOMORROW: DayView = {
  ...TODAY,
  kind: "tomorrow",
  day: "2026-10-18",
  actual_updated_at: null,
  cards: null,
  departure: { ...TODAY.departure!, source: "tonight", badge: "reliable", expected_kwh: null, gap_points: null },
  weather: { ...TODAY.weather, today_estimate_kwh: 9.5, today_gap_percent: -12 },
};

export const WITHOUT_BATTERY: DayView = { ...TODAY, battery_capacity_kwh: null, departure: null };
// Maison sans installation solaire (lot 7.4) : heures creuses, Tempo ou prix dynamiques seulement.
export const WITHOUT_SOLAR: DayView = { ...WITHOUT_BATTERY, solar: false };

/** Plan d'avant les indicateurs et les explications (lots 3.6 et 3.7). */
export const WITHOUT_INSIGHTS: DayView = { ...TODAY, indicators: null, explanations: [], recommendation: null };

const weekDay = (day: string, detail: WeekDay["detail_view"], devices: WeekDay["devices"] = []): WeekDay => ({
  day,
  detail_view: detail,
  production_kwh: 12.34,
  weather: "sunny",
  soc_start_percent: 40,
  soc_end_percent: 55,
  soc_max_percent: 98,
  grid_import_kwh: 1.5,
  grid_import_peak_kwh: 0.25,
  grid_export_kwh: 0.75,
  devices,
  notices: [],
});

const WEEK_POINTS: WeekPoint[] = ["2026-10-17", "2026-10-18", "2026-10-19"].flatMap((day) =>
  Array.from({ length: 24 }, (_, hour) => ({
    day,
    hour,
    off_peak: hour < 6 || hour >= 22,
    soc_percent: 50,
    soc_kwh: 2.56,
    production_kwh: hour >= 8 && hour < 18 ? 1 : 0,
    consumption_kwh: 0.4,
  })),
);

export const WEEK: WeekView = {
  computed_at: "2026-10-17T13:59:00",
  manual: true,
  seconds: 4.2,
  days: [
    weekDay("2026-10-17", "today", [{ device: "Lave-linge", start_min: 605, end_min: 690 }]),
    {
      ...weekDay("2026-10-18", "tomorrow"),
      weather: "cloudy",
      notices: [{ code: "tache_reportee", info: true, text: "Sèche-linge reporté au lundi 19 octobre." }],
    },
    weekDay("2026-10-19", null),
  ],
  points: WEEK_POINTS,
  floor_percent: 12,
  now_index: 13.5,
  notices: [{ code: "horizon_incomplet", info: false, text: "Prévision manquante pour le 23 octobre." }],
  waiting_not_assigned: true,
};

export const WEEK_WITHOUT_BATTERY: WeekView = {
  ...WEEK,
  days: WEEK.days.map((day) => ({ ...day, soc_start_percent: null, soc_end_percent: null, soc_max_percent: null })),
  points: WEEK_POINTS.map((point) => ({ ...point, soc_percent: null, soc_kwh: null })),
};
