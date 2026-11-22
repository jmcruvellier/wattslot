// Raison d'un créneau en quelques mots (« 100 % solaire », « heures creuses »), tirée des raisons
// structurées du plan : pour la ligne sous « Prochaine action » et l'agenda. La phrase complète
// du serveur reste disponible, dépliée à la demande.

import type { DeviceExplanation } from "./types";

type Translate = (key: string, params?: Record<string, string | number>) => string;

export function shortReason(explanation: DeviceExplanation["explanation"], t: Translate): string | null {
  const reasons = explanation?.raisons ?? [];
  const solar = reasons.find((reason) => reason.code === "solar_share");
  const percent = Number(solar?.params?.percent);
  if (solar && percent > 0) return t("plan.reason.solar", { pct: percent });
  if (reasons.some((reason) => reason.code === "cheap_hours")) return t("plan.reason.cheap");
  return null;
}
