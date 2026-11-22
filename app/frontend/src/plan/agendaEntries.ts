// Agenda d'un jour (lot 6b.4) : la frise lue comme une liste d'actions datées, triées par
// heure. Appareils à cycle, durées à placer (« Piscine, 1 h »), phases de la batterie (charge,
// relais du soir) et son maximum. Pour les heures déjà mesurées (hier en entier, aujourd'hui
// jusqu'au dernier relevé), la batterie est racontée d'après ses mesures, pas d'après le plan :
// le plan gardé assemble des calculs horaires qui repartent chacun du niveau mesuré, et son
// maximum pouvait tomber après le début d'une décharge prévue (constaté le 22/11/2026). Le
// résumé de la journée donne la plage où le soleil produit le plus.

import { hourOfDay } from "../i18n/homeTime";
import type { OtherStart } from "./OtherStarts";
import type { Bar, DayView, TimelineRow } from "./types";

export type AgendaEntry =
  | {
      kind: "cycle";
      minute: number;
      end: number;
      device: string;
      explanation: string | null;
      // Autres départs proposés par le plan et départ choisi : dépliés sous l'explication.
      alternatives: OtherStart[];
      chosen: boolean;
      // À droite de la ligne : l'énergie prévue, ou mesurée une fois le cycle vu (« lancé »).
      energy_kwh: number;
      launched: boolean;
      actual_kwh: number | null;
    }
  | { kind: "runtime"; minute: number; end: number; device: string; mode: string | null }
  // `phase` : les batteries d'une phase (calcul par phase), 0 : celles qui compensent le total.
  | { kind: "battery_charge" | "battery_discharge"; minute: number; end: number; phase?: number | null }
  | { kind: "battery_max"; minute: number; percent: number };

const toMinute = (hour: number) => Math.round(hour * 60);
// Heure mesurée, au pas de cinq minutes : « 8h25 », pas « 8h23 ».
const toMinute5 = (hour: number) => Math.round(hour * 12) * 5;

// Bloc mesuré de la batterie trop petit pour une ligne de l'agenda.
const MIN_MEASURED_KWH = 0.1;
// Un mouvement prévu qui prolonge le dernier mesuré de même sens, à moins d'une heure : une
// seule ligne (« se charge jusqu'à 15h »), pas deux.
const SAME_MOVE_MIN = 60;

type BatteryEntry = Extract<AgendaEntry, { kind: "battery_charge" | "battery_discharge" }>;

/** Heure jusqu'à laquelle la journée est mesurée : toute la veille, aujourd'hui jusqu'au dernier
 * relevé, rien pour un jour à venir. */
function measuredUntil(view: DayView): number {
  if (view.kind === "yesterday") return 24;
  if (view.kind !== "today" || !view.actual_updated_at) return 0;
  return hourOfDay(new Date(view.actual_updated_at));
}

/** Phases de la batterie d'une ligne de la frise : mesurées jusqu'à ``limit``, prévues ensuite ;
 * sans mesure, les phases prévues. */
function batteryEntries(row: TimelineRow, limit: number): BatteryEntry[] {
  const phase = row.phase ?? null;
  const kind = (bar: Bar) => `battery_${bar.action}` as BatteryEntry["kind"];
  const planned = row.planned.filter((bar) => !bar.carried && bar.action);
  const measured = row.actual.filter((bar) => bar.action && bar.energy_kwh >= MIN_MEASURED_KWH);
  if (limit <= 0 || measured.length === 0) {
    return planned.map((bar) => ({ kind: kind(bar), minute: toMinute(bar.start_hour), end: toMinute(bar.end_hour), phase }));
  }
  const found: BatteryEntry[] = measured.map((bar) => ({
    kind: kind(bar),
    minute: toMinute5(bar.start_hour),
    end: toMinute5(bar.end_hour),
    phase,
  }));
  for (const bar of planned.filter((one) => one.end_hour > limit)) {
    const start = toMinute(Math.max(bar.start_hour, limit));
    const last = [...found].reverse().find((entry) => entry.kind === kind(bar));
    if (bar.start_hour < limit && last && start - last.end <= SAME_MOVE_MIN) last.end = toMinute(bar.end_hour);
    else found.push({ kind: kind(bar), minute: start, end: toMinute(bar.end_hour), phase });
  }
  return found;
}

/** Plus haut niveau de la batterie et son heure : d'après les mesures de fin d'heure pour les
 * heures mesurées, le plan pour la suite ; sans mesure, le maximum du plan (résumé du serveur). */
function batteryMax(view: DayView, limit: number): { minute: number; percent: number } {
  const planned = { minute: toMinute(view.summary.soc_max_hour), percent: view.summary.soc_max_percent };
  const measured = (hour: (typeof view.hours)[number]) =>
    hour.hour < limit && hour.soc_actual_percent != null ? hour.soc_actual_percent : null;
  if (!view.hours.some((hour) => measured(hour) !== null)) return planned;
  let best: { minute: number; percent: number } | null = null;
  for (const hour of view.hours) {
    const level = measured(hour) ?? hour.soc_percent;
    // Niveau de fin d'heure : atteint à l'heure suivante.
    if (level != null && (best === null || level > best.percent)) best = { minute: (hour.hour + 1) * 60, percent: level };
  }
  const start = view.departure?.soc_percent;
  if (best === null) return planned;
  // Jamais plus haut qu'à minuit : le maximum est le niveau de départ.
  return start != null && start >= best.percent ? { minute: 0, percent: start } : best;
}

export function agenda(view: DayView): AgendaEntry[] {
  const explanations = new Map(view.explanations.map((item) => [item.device, item]));
  const statuses = new Map(view.timeline.statuses.map((status) => [status.device, status]));
  const entries: AgendaEntry[] = [];
  const limit = measuredUntil(view);
  for (const row of view.timeline.rows) {
    if (row.kind === "battery") {
      entries.push(...batteryEntries(row, limit));
      continue;
    }
    // La fin d'un cycle commencé la veille n'est pas une action du jour.
    for (const bar of row.planned.filter((planned) => !planned.carried)) {
      const minute = toMinute(bar.start_hour);
      const end = toMinute(bar.end_hour);
      if (row.kind === "cycle") {
        // Identité du cycle : l'équipement, et son rang à partir de son deuxième cycle du jour.
        const cycle = bar.cycle ?? row.device;
        const why = explanations.get(cycle);
        const status = statuses.get(cycle);
        entries.push({
          kind: "cycle",
          minute,
          end,
          device: cycle,
          explanation: why?.text ?? null,
          alternatives: (why?.explanation?.alternatives ?? []).map((other) => ({
            start_min: other.debut_min,
            cost_eur_delta: other.ecart_cout_eur,
            import_kwh_delta: other.ecart_soutirage_kwh,
          })),
          chosen: why?.explanation?.choisi ?? false,
          energy_kwh: bar.energy_kwh,
          launched: status != null && status.actual_start_min !== null,
          actual_kwh: status?.actual_kwh ?? null,
        });
      } else {
        entries.push({ kind: "runtime", minute, end, device: row.device, mode: bar.mode });
      }
    }
  }
  const battery = view.timeline.rows.some((row) => row.kind === "battery");
  if (battery && view.battery_capacity_kwh !== null) {
    const top = batteryMax(view, limit);
    // Le niveau n'est connu qu'en fin d'heure : si une décharge commence dans l'heure qui
    // précède, le plus haut a été atteint juste avant elle, pas après.
    const after = entries.find(
      (entry) => entry.kind === "battery_discharge" && entry.minute > top.minute - 60 && entry.minute <= top.minute,
    );
    entries.push({ kind: "battery_max", minute: after ? after.minute : top.minute, percent: top.percent });
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

/** Explications qu'aucune ligne de l'agenda ne porte (la batterie, un appareil sans créneau). */
export function otherExplanations(view: DayView, entries: AgendaEntry[]) {
  const shown = new Set(entries.flatMap((entry) => (entry.kind === "cycle" ? [entry.device] : [])));
  return view.explanations.filter((item) => !shown.has(item.device));
}

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
