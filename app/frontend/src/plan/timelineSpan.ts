// Place libre d'un bloc du Planning des équipements pour y écrire son énergie (lot 7.1).

import type { Bar } from "./types";

/** Plus grande partie de ``items[index]`` qu'aucun bloc dessiné après lui dans le même couloir ne
 * recouvre (les courtes décharges posées sur une charge…), en heures : l'énergie y est centrée. */
export function freeSpan(items: Bar[], index: number): [number, number] {
  const bar = items[index];
  const covers = items
    .slice(index + 1)
    .filter((other) => other.start_hour < bar.end_hour && other.end_hour > bar.start_hour)
    .map((other) => [Math.max(other.start_hour, bar.start_hour), Math.min(other.end_hour, bar.end_hour)])
    .sort((a, b) => a[0] - b[0]);
  const gaps: [number, number][] = [];
  let cursor = bar.start_hour;
  for (const [start, end] of covers) {
    if (start > cursor) gaps.push([cursor, start]);
    cursor = Math.max(cursor, end);
  }
  if (cursor < bar.end_hour) gaps.push([cursor, bar.end_hour]);
  const none: [number, number] = [bar.start_hour, bar.start_hour];
  return gaps.reduce((best, gap) => (gap[1] - gap[0] > best[1] - best[0] ? gap : best), none);
}
