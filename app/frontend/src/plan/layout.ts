// Disposition du dashboard (lot 5.5) : ordre et cartes masquées de chaque vue, indicateurs ;
// gardée dans l'installation (`/api/settings/dashboard`, `views/layout.py`). Une carte
// n'apparaît que si l'installation la justifie (lot 5.3) et si elle n'est pas masquée.

import type { DayView, Indicators, ViewKind, WeekView } from "./types";

export type DayCardId = "summary" | "timeline" | "soc" | "grid" | "energy" | "indicators" | "explanations";
export type WeekCardId = "production" | "consumption" | "soc" | "days";
export type CardId = DayCardId | WeekCardId;
export type IndicatorKey = keyof Indicators;

export interface ViewLayout {
  order: CardId[];
  hidden: CardId[];
}

export interface IndicatorLayout {
  highlight: IndicatorKey | null; // aucun : celui de l'objectif du calcul
  hidden: IndicatorKey[];
}

export interface DashboardLayout {
  yesterday: ViewLayout;
  today: ViewLayout;
  tomorrow: ViewLayout;
  week: ViewLayout;
  indicators: IndicatorLayout;
  default?: boolean;
}

export const DAY_CARDS: DayCardId[] = ["summary", "timeline", "soc", "grid", "energy", "indicators", "explanations"];
export const WEEK_CARDS: WeekCardId[] = ["production", "consumption", "soc", "days"];

export const INDICATORS: IndicatorKey[] = [
  "cost_eur",
  "import_kwh",
  "export_kwh",
  "self_consumption_percent",
  "co2_kg",
  "end_soc_percent",
  "battery_throughput_kwh",
];

const BATTERY_ONLY: IndicatorKey[] = ["end_soc_percent", "battery_throughput_kwh"];

/** Indicateurs que le plan et l'installation justifient, dans leur ordre. */
export function availableIndicators(view: DayView): IndicatorKey[] {
  const indicators = view.indicators;
  if (!indicators) return [];
  return INDICATORS.filter(
    (key) => indicators[key] !== null && (view.battery_capacity_kwh !== null || !BATTERY_ONLY.includes(key)),
  );
}

/** Disposition par défaut, celle du serveur sans personnalisation (avant sa lecture ou s'il ne
 * répond pas). */
export const DEFAULT_LAYOUT: DashboardLayout = {
  yesterday: { order: [...DAY_CARDS], hidden: [] },
  today: { order: [...DAY_CARDS], hidden: [] },
  tomorrow: { order: [...DAY_CARDS], hidden: [] },
  week: { order: [...WEEK_CARDS], hidden: [] },
  indicators: { highlight: null, hidden: [] },
  default: true,
};

/** Cartes d'une vue de jour que l'installation et le plan justifient. */
export function availableDayCards(view: DayView): DayCardId[] {
  return DAY_CARDS.filter((id) => {
    if (id === "soc") return view.battery_capacity_kwh !== null;
    if (id === "indicators") return view.indicators !== null;
    if (id === "explanations") return view.explanations.length > 0 || view.recommendation !== null;
    return true; // la frise vide dit pourquoi rien n'est planifié
  });
}

/** Cartes de la semaine que l'installation et l'horizon justifient. */
export function availableWeekCards(view: WeekView): WeekCardId[] {
  return WEEK_CARDS.filter((id) => {
    if (id === "days") return true;
    if (!view.points.length) return false;
    return id !== "soc" || view.points.some((point) => point.soc_percent !== null);
  });
}

/** Cartes affichées, dans l'ordre choisi : disponibles et non masquées. */
export function shownCards<T extends CardId>(layout: ViewLayout, available: T[]): T[] {
  return layout.order.filter((id): id is T => available.includes(id as T) && !layout.hidden.includes(id));
}

/** Échange une carte affichée avec sa voisine affichée (les cartes absentes gardent leur place). */
export function move(layout: ViewLayout, shown: CardId[], id: CardId, step: -1 | 1): ViewLayout {
  const neighbour = shown[shown.indexOf(id) + step];
  if (neighbour === undefined) return layout;
  const order = [...layout.order];
  const a = order.indexOf(id);
  const b = order.indexOf(neighbour);
  [order[a], order[b]] = [order[b], order[a]];
  return { ...layout, order };
}

export function hide(layout: ViewLayout, id: CardId): ViewLayout {
  return layout.hidden.includes(id) ? layout : { ...layout, hidden: [...layout.hidden, id] };
}

export function restore(layout: ViewLayout, id: CardId): ViewLayout {
  return { ...layout, hidden: layout.hidden.filter((hidden) => hidden !== id) };
}

export function layoutOf(layout: DashboardLayout, kind: ViewKind): ViewLayout {
  return layout[kind];
}
