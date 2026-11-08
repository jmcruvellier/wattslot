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

/** Haut de l'axe : un peu au-dessus du plus haut point, arrondi à 1, 2 ou 5 × 10ⁿ. */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value * 1.1));
  const step = [1, 2, 5, 10].find((s) => s * magnitude >= value * 1.1) ?? 10;
  return step * magnitude;
}

// Part de la hauteur où tombe le seuil d'alerte : assez haut pour montrer la marge qui reste, avec
// un peu de place au-dessus.
const THRESHOLD_SHARE = 0.8;

/** ``value`` arrondi vers le haut à deux chiffres significatifs (1,375 → 1,4 ; 33,6 → 34). */
function ceilTwoDigits(value: number): number {
  const unit = 10 ** (Math.floor(Math.log10(value)) - 1);
  return Math.ceil(value / unit - 1e-9) * unit;
}

/** Haut de l'axe d'une courbe : avec un seuil d'alerte, la ligne tombe vers 80 % de la hauteur,
 * quelle que soit sa valeur ; une valeur au-delà agrandit l'axe pour rester visible. Sans seuil,
 * l'arrondi de ``niceMax``. */
export function axisTop(highest: number, threshold?: number | null): number {
  if (threshold == null || threshold <= 0) return niceMax(highest);
  const top = ceilTwoDigits(threshold / THRESHOLD_SHARE);
  return highest <= top ? top : niceMax(highest);
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
