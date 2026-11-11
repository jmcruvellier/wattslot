// Nom des batteries dans la frise et l'agenda : la batterie de la maison, ou, quand le plan est
// calculé par phase, les batteries d'une phase (1, 2 ou 3) ou celles qui compensent le total (0).

import type { TimelineRow } from "./types";

type Translate = (key: string, params?: Record<string, string | number>) => string;

export function batteryLabel(phase: number | null | undefined, t: Translate): string {
  if (phase == null) return t("plan.timeline.battery");
  return phase === 0 ? t("plan.timeline.battery_total") : t("plan.timeline.battery_phase", { number: phase });
}

// Nom d'une ligne de la frise : l'équipement, ou sa batterie.
export function rowLabel(row: TimelineRow, t: Translate): string {
  return row.kind === "battery" ? batteryLabel(row.phase, t) : row.device;
}
