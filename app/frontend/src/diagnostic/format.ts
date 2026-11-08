// Mise en forme des valeurs de la page de diagnostic, dans la langue de l'interface.

import type { Role } from "../home/types";
import type { Language } from "../i18n/translate";
import { zoned } from "../i18n/homeTime";

export function unitOf(role: Role): string {
  if (role === "StateOfCharge") return "%";
  return role.startsWith("Power") ? "W" : "kWh";
}

export function formatNumber(language: Language, value: number, digits = 2): string {
  return new Intl.NumberFormat(language, { maximumFractionDigits: digits }).format(value);
}

/** Pourcentage (« 2,5 % », « 85 % ») : une décimale sous 10 %. */
export function formatPercent(language: Language, value: number): string {
  return new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: value < 10 ? 1 : 0 }).format(
    value / 100,
  );
}

export function formatDate(language: Language, time: string | null): string {
  return time ? new Date(time).toLocaleString(language, zoned()) : "—";
}

/** Durée écoulée entre `time` et `reference`, en langage courant (« il y a 5 minutes »). */
export function formatAge(language: Language, time: string | null, reference: string): string {
  if (!time) return "—";
  const seconds = Math.round((Date.parse(time) - Date.parse(reference)) / 1000);
  const format = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return format.format(seconds, "second");
}
