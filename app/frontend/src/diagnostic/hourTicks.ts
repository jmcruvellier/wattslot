// Graduations horaires de l'axe des abscisses des courbes de ressources : chaque heure pleine
// (à l'heure de la maison) entre le premier et le dernier relevé, espacées pour que les libellés
// ne se chevauchent pas. Sur un écran étroit, une heure sur 2, 3, 4, 6 ou 12 seulement ; les
// heures trop proches des bords, où s'écrivent l'heure de début et celle de fin, sont omises.

import { minuteOfDay } from "../i18n/homeTime";

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
// Place d'un libellé (« 19:00 ») avec sa marge, en pixels.
export const TICK_MIN_PX = 56;
const STEPS = [1, 2, 3, 4, 6, 12];

/** Instants des heures pleines à graduer entre ``start`` et ``end`` (millisecondes), pour un
 * axe de ``widthPx`` pixels ; aucun sans largeur connue. ``minuteOf`` donne la minute du jour
 * d'un instant (fuseau de la maison par défaut). */
export function hourTicks(
  start: number,
  end: number,
  widthPx: number,
  minuteOf: (moment: Date) => number = minuteOfDay,
): number[] {
  const span = end - start;
  if (widthPx <= 0 || span <= 0) return [];
  const pxPerHour = (widthPx * HOUR_MS) / span;
  const step = STEPS.find((s) => s * pxPerHour >= TICK_MIN_PX);
  if (step === undefined) return [];
  // Première heure pleine à partir de ``start`` (les fuseaux ont des écarts en minutes entières).
  const minute = minuteOf(new Date(start));
  let tick = start - (start % MINUTE_MS) + ((60 - (minute % 60)) % 60) * MINUTE_MS;
  if (tick < start) tick += HOUR_MS;
  // Distance minimale aux bords : les libellés de début et de fin y sont écrits.
  const margin = (TICK_MIN_PX * span) / widthPx;
  const ticks: number[] = [];
  for (; tick <= end; tick += HOUR_MS) {
    const hour = Math.round(minuteOf(new Date(tick)) / 60) % 24;
    if (hour % step !== 0) continue;
    if (tick - start < margin || end - tick < margin) continue;
    ticks.push(tick);
  }
  return ticks;
}
