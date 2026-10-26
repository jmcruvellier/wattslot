import { describe, expect, it } from "vitest";

import { energyPoints, socPoints } from "./dayPoints";
import type { HourPoint } from "./types";

// Journée simple : 24 heures, prévu = h + 1 kWh, mesuré = 2 × h décimales ; heures 0 à 20
// complètes, 21 en cours, 22 et 23 à venir.
function day(): HourPoint[] {
  return Array.from({ length: 24 }, (_, h) => ({
    hour: h,
    off_peak: h < 6,
    production_kwh: h + 1,
    consumption_kwh: (h + 1) * 2,
    grid_import_kwh: h,
    grid_export_kwh: 0,
    battery_charge_kwh: 0,
    battery_discharge_kwh: 0,
    soc_percent: 50,
    production_actual_kwh: h <= 21 ? (h + 1) * 1.5 : null,
    consumption_actual_kwh: h <= 21 ? (h + 1) * 3 : null,
    grid_import_actual_kwh: h <= 21 ? h : null,
    grid_export_actual_kwh: h <= 21 ? 0 : null,
    soc_actual_percent: h <= 21 ? 50 + h : null,
  }));
}

describe("energyPoints", () => {
  it("couvre chaque graduation de 0 h à 24 h, triées par abscisse", () => {
    const points = energyPoints(day(), null);
    const xs = points.map((p) => p.x);
    expect(xs).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]);
    // Le niveau de la première heure est tenu de 0 h à 1 h.
    expect(points[0]).toMatchObject({ x: 0, production: 1, consumption: 2 });
    expect(points[1]).toMatchObject({ x: 1, production: 1, consumption: 2 });
    // L'énergie de l'heure h est posée à sa fin (h + 1) ; mesurée aussi.
    expect(points[10]).toMatchObject({ x: 10, production: 10, consumption: 20, productionActual: 15, consumptionActual: 30 });
    expect(points[24]).toMatchObject({ x: 24, production: 24, consumption: 48, productionActual: null });
  });

  it("sépare la tranche en cours : prévu à sa fin, relevé extrapolé au milieu", () => {
    // Relevé à 21 h 49 : 49 minutes écoulées, mesure partielle de l'heure 21.
    const points = energyPoints(day(), 21 + 49 / 60);
    const xs = points.map((p) => p.x);
    expect(xs.slice(-4)).toEqual([21 + 49 / 60, 22, 23, 24]);
    // Le point prévu de l'heure 21 n'a pas bougé : à 22 h, sans mesure.
    expect(points.find((p) => p.x === 22)).toMatchObject({ x: 22, production: 22, consumption: 44, productionActual: null });
    expect(points.find((p) => p.x === 24)).toMatchObject({ x: 24, production: 24, consumption: 48, productionActual: null });
    // Le relevé : équivalent horaire de la mesure partielle (× 60 / 49).
    const releve = points.find((p) => p.x === 21 + 49 / 60);
    expect(releve).toMatchObject({
      production: null,
      productionActual: Math.round((22 * 1.5 * 60) / 49 * 1000) / 1000,
      consumptionActual: Math.round((22 * 3 * 60) / 49 * 1000) / 1000,
    });
    // Les abscisses sont strictement croissantes : Recharts relie les points dans l'ordre.
    expect([...xs].sort((a, b) => a - b)).toEqual(xs);
  });

  it("masque la mesure de la tranche en cours de moins de dix minutes", () => {
    const points = energyPoints(day(), 21 + 5 / 60);
    const releve = points.find((p) => p.x === 21 + 5 / 60);
    expect(releve).toMatchObject({ productionActual: null, consumptionActual: null });
  });
});

describe("socPoints", () => {
  it("va de 0 h (départ à minuit) à 24 h, trié par abscisse", () => {
    const points = socPoints(day(), null, 34);
    const xs = points.map((p) => p.x);
    expect(xs).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]);
    expect(points[0]).toMatchObject({ x: 0, soc: 34, socActual: 34 });
    expect(points.find((p) => p.x === 22)).toMatchObject({ x: 22, soc: 50, socActual: 71 });
  });

  it("sépare la tranche en cours : prévu conservé à sa fin, mesure sur le relevé", () => {
    // Régression : le point prévu de l'heure en cours ne doit pas être déplacé par le
    // relevé (le graphe sautait alors de 22 h 15 à 24 h sans point à 23 h), et la courbe
    // mesurée doit s'arrêter SUR le relevé, pas au point précédent.
    const points = socPoints(day(), 21 + 49 / 60, 34);
    const xs = points.map((p) => p.x);
    expect(xs).toContain(21 + 49 / 60);
    expect(points.find((p) => p.x === 22)).toMatchObject({ x: 22, soc: 50, socActual: null });
    expect(points.find((p) => p.x === 21 + 49 / 60)).toMatchObject({ soc: null, socActual: 71 });
    // Le point suivant la mesure est bien plus loin : la courbe mesurée s'arrête au relevé.
    const apres = xs.findIndex((x) => x === 21 + 49 / 60);
    expect(xs[apres + 1]).toBe(22);
  });

  it("sans départ à minuit, la courbe commence à la fin de la première heure", () => {
    const points = socPoints(day(), null, null);
    expect(points.map((p) => p.x)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]);
  });
});
