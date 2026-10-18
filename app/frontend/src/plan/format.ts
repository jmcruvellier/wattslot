// Mise en forme des nombres et des heures des vues, avec les arrondis du dashboard de la v1 :
// 2 décimales pour les kWh, 0 pour les pourcentages ; séparateur décimal de la langue (lot 5.7).

import { formatNumber, type Language } from "../i18n/translate";

// Langue des nombres (virgule décimale en français…), tenue par le fournisseur de la langue.
let numberLanguage: Language = "en";

export function setNumberLanguage(language: Language): void {
  numberLanguage = language;
}

export function kwh(value: number | null | undefined, decimals = 2): string {
  return value === null || value === undefined ? "—" : formatNumber(numberLanguage, value, decimals);
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : formatNumber(numberLanguage, value, 0);
}

/** Graduation d'un axe de graphique : « 0,75 kWh », « -0,3 kWh », « 50 % ». Espace insécable
 * avant l'unité : Recharts ne coupe pas la graduation sur deux lignes. */
export function axisTick(unit: string): (value: number) => string {
  return (value) => `${formatNumber(numberLanguage, value)}\u00a0${unit}`;
}

/** Minutes depuis minuit : « 10h05 » / « 10:05 ». */
export function clock(minutes: number, language: Language): string {
  const h = Math.floor(minutes / 60) % 24;
  const m = Math.round(minutes % 60);
  const mm = String(m).padStart(2, "0");
  return language === "fr" ? `${h}h${mm}` : `${h}:${mm}`;
}

/** Heure fractionnaire : « 14h » pour une heure pile, « 14h35 » sinon. */
export function hour(value: number, language: Language): string {
  if (value % 1 === 0) return language === "fr" ? `${value}h` : `${value}:00`;
  return clock(value * 60, language);
}

/** Durée en minutes : « 1h30 », « 50 min ». */
export function duration(minutes: number, language: Language): string {
  const h = Math.floor(Math.abs(minutes) / 60);
  const m = Math.abs(minutes) % 60;
  if (language === "fr") return h ? `${h}h${m ? String(m).padStart(2, "0") : ""}` : `${m} min`;
  return h ? `${h} h${m ? ` ${m} min` : ""}` : `${m} min`;
}

export function time(iso: string, language: Language): string {
  return new Date(iso).toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });
}

export function longDate(iso: string, language: Language): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(language, { weekday: "long", day: "numeric", month: "long" });
}
