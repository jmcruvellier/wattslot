// Points des graphes du jour (Batterie/SoC, Production et consommation) : la géométrie de
// chaque courbe, testée à part (dayPoints.test.ts) — Recharts relie les points dans l'ordre
// du tableau, ces fonctions les rendent triés par abscisse.

import { hour } from "./format";
import type { HourPoint } from "./types";

// La tranche en cours ne compte que ses minutes écoulées : en dessous, pas de point (v1 :
// dix minutes minimum, l'équivalent horaire multiplierait trop quelques centièmes de kWh).
const MINUTES_TRANCHE_EN_COURS = 10;

/** Heure d'un point dans une info-bulle : l'instant réel qu'il décrit — « 21 h » pour une
 * heure pleine, « 21 h 22 » pour le relevé au milieu de sa tranche. */
export function instantLabel(x: number, lang: "fr" | "en"): string {
  return x % 1 === 0 ? `${x}h` : hour(x, lang);
}

/** Énergie réelle d'une heure ; celle de la tranche en cours est extrapolée en équivalent
 * horaire (mesure × 60 / minutes écoulées, convention v1 : sans cela, la courbe réelle
 * plonge sur son dernier point, qui ne compte que le début de l'heure). */
function equivalentHoraire(value: number | null, minutes: number | null): number | null {
  if (minutes === null) return value;
  if (value === null || minutes < MINUTES_TRANCHE_EN_COURS) return null;
  return Math.round(((value * 60) / minutes) * 1000) / 1000;
}

export interface EnergyPoint {
  x: number;
  production: number | null;
  consumption: number | null;
  productionActual: number | null;
  consumptionActual: number | null;
}

/** Points du graphe de production/consommation — triés par abscisse, Recharts relie les
 * points dans l'ordre du tableau. L'énergie de l'heure h est posée à sa fin (h + 1), comme
 * le SoC ; le niveau de la première heure est aussi tenu de 0 h à 1 h, pour couvrir toute
 * la journée (25 graduations pour 24 heures). La tranche en cours a deux points : le prévu
 * à sa fin, le relevé au milieu (équivalent horaire de la mesure partielle). */
export function energyPoints(hours: HourPoint[], readingHour: number | null): EnergyPoint[] {
  const data: EnergyPoint[] = [];
  for (const h of hours) {
    const enCours = readingHour !== null && Math.floor(readingHour) === h.hour;
    const minutes = enCours ? Math.round((readingHour - h.hour) * 60) : null;
    data.push({
      x: h.hour + 1,
      production: h.production_kwh,
      consumption: h.consumption_kwh,
      productionActual: enCours ? null : h.production_actual_kwh,
      consumptionActual: enCours ? null : h.consumption_actual_kwh,
    });
    if (enCours) {
      data.push({
        x: readingHour,
        production: null,
        consumption: null,
        productionActual: equivalentHoraire(h.production_actual_kwh, minutes),
        consumptionActual: equivalentHoraire(h.consumption_actual_kwh, minutes),
      });
    }
  }
  const first = hours.find((h) => h.hour === 0);
  if (first) {
    const enCours = readingHour !== null && readingHour < 1;
    const minutes = enCours ? Math.round(readingHour * 60) : null;
    data.push({
      x: 0,
      production: first.production_kwh,
      consumption: first.consumption_kwh,
      productionActual: enCours ? equivalentHoraire(first.production_actual_kwh, minutes) : first.production_actual_kwh,
      consumptionActual: enCours ? equivalentHoraire(first.consumption_actual_kwh, minutes) : first.consumption_actual_kwh,
    });
  }
  return data.sort((a, b) => a.x - b.x);
}

export interface SocPoint {
  x: number;
  soc: number | null;
  socActual: number | null;
}

/** Points du graphe de SoC — triés par abscisse, Recharts relie les points dans l'ordre du
 * tableau. Le SoC d'une heure est celui de fin d'heure (modèle du backend) : posé à
 * l'instant h + 1, le point « 23 h » est donc le SoC atteint à minuit. La tranche en cours
 * a deux points : le prévu à sa fin, la dernière mesure (« maintenant ») sur le relevé.
 * Le départ à minuit complète la courbe à 0 h : de 0 h à 24 h. */
export function socPoints(hours: HourPoint[], readingHour: number | null, midnight: number | null): SocPoint[] {
  const data: SocPoint[] = [];
  for (const h of hours) {
    const enCours = readingHour !== null && Math.floor(readingHour) === h.hour;
    data.push({ x: h.hour + 1, soc: h.soc_percent, socActual: enCours ? null : h.soc_actual_percent });
    if (enCours) data.push({ x: readingHour, soc: null, socActual: h.soc_actual_percent });
  }
  if (midnight !== null) {
    const plan = hours.some((h) => h.soc_percent !== null);
    const actual = hours.some((h) => h.soc_actual_percent !== null);
    data.push({ x: 0, soc: plan ? midnight : null, socActual: actual ? midnight : null });
  }
  return data.sort((a, b) => a.x - b.x);
}
