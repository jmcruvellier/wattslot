// Agenda d'un jour (lot 6b.4) : la frise prévue lue comme une liste d'actions datées, triées par
// heure. Appareils à cycle (« Lancez… »), durées à placer (« Piscine, 1 h »), phases de la
// batterie (charge, relais du soir) et son maximum. Le résumé de la journée donne la qualité du
// soleil et la plage où il produit le plus.

import type { DayView } from "./types";

export type AgendaEntry =
  | { kind: "cycle"; minute: number; end: number; device: string; explanation: string | null }
  | { kind: "runtime"; minute: number; end: number; device: string; mode: string | null }
  | { kind: "battery_charge" | "battery_discharge"; minute: number; end: number }
  | { kind: "battery_max"; minute: number; percent: number };

const toMinute = (hour: number) => Math.round(hour * 60);

export function agenda(view: DayView): AgendaEntry[] {
  const explanations = new Map(view.explanations.map((item) => [item.device, item.text]));
  const entries: AgendaEntry[] = [];
  for (const row of view.timeline.rows) {
    for (const bar of row.planned) {
      const minute = toMinute(bar.start_hour);
      const end = toMinute(bar.end_hour);
      if (row.kind === "battery") {
        if (bar.action) entries.push({ kind: `battery_${bar.action}`, minute, end });
      } else if (row.kind === "cycle") {
        entries.push({ kind: "cycle", minute, end, device: row.device, explanation: explanations.get(row.device) ?? null });
      } else {
        entries.push({ kind: "runtime", minute, end, device: row.device, mode: bar.mode });
      }
    }
  }
  const battery = view.timeline.rows.some((row) => row.kind === "battery");
  if (battery && view.battery_capacity_kwh !== null) {
    entries.push({ kind: "battery_max", minute: toMinute(view.summary.soc_max_hour), percent: view.summary.soc_max_percent });
  }
  // À la même heure : les actions à faire d'abord, puis la batterie dans l'ordre de sa journée
  // (début de charge, maximum, relais du soir).
  return entries.sort((a, b) => a.minute - b.minute || ORDER[a.kind] - ORDER[b.kind]);
}

const ORDER: Record<AgendaEntry["kind"], number> = {
  cycle: 0,
  runtime: 0,
  battery_charge: 1,
  battery_max: 2,
  battery_discharge: 3,
};

/** Plage [début, fin[ en heures où le soleil produit au moins la moitié de son maximum. */
export function sunWindow(view: DayView): [number, number] | null {
  const production = view.hours.map((h) => h.production_kwh);
  const peak = Math.max(0, ...production);
  if (peak <= 0) return null;
  const strong = view.hours.filter((h) => h.production_kwh >= peak / 2).map((h) => h.hour);
  return [Math.min(...strong), Math.max(...strong) + 1];
}

/** Index de la première entrée encore à venir (Aujourd'hui), pour le repère « maintenant ». */
export function firstUpcoming(entries: AgendaEntry[], nowMinute: number): number {
  const index = entries.findIndex((entry) => entry.minute >= nowMinute);
  return index < 0 ? entries.length : index;
}
