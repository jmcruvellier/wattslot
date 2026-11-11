import { describe, expect, it } from "vitest";

import { TICK_MIN_PX, hourTicks } from "./hourTicks";

const HOUR = 3_600_000;
const MINUTE = 60_000;
// Fuseau UTC pour les tests : la minute du jour se lit sur l'instant.
const utcMinute = (moment: Date) => moment.getUTCHours() * 60 + moment.getUTCMinutes();
// De 19:22 à 19:21 le lendemain, comme la page d'état.
const START = Date.UTC(2026, 10, 10, 19, 22, 30);
const END = START + 24 * HOUR - MINUTE;

const hours = (ticks: number[]) => ticks.map((t) => new Date(t).getUTCHours());

describe("hourTicks", () => {
  it("gradue chaque heure pleine sur un écran large", () => {
    const ticks = hourTicks(START, END, 1700, utcMinute);
    expect(hours(ticks)).toEqual([21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]);
    ticks.forEach((t) => expect(t % HOUR).toBe(0));
  });

  it("espace les heures pour que les libellés ne se chevauchent pas", () => {
    const width = 360;
    const ticks = hourTicks(START, END, width, utcMinute);
    expect(ticks.length).toBeGreaterThan(0);
    const px = (t: number) => ((t - START) / (END - START)) * width;
    for (let i = 1; i < ticks.length; i += 1) expect(px(ticks[i]) - px(ticks[i - 1])).toBeGreaterThanOrEqual(TICK_MIN_PX);
    // Une heure sur 4 à cette largeur, alignée sur minuit.
    hours(ticks).forEach((h) => expect(h % 4).toBe(0));
  });

  it("laisse la place des heures de début et de fin", () => {
    const width = 1700;
    const ticks = hourTicks(START, END, width, utcMinute);
    const margin = (TICK_MIN_PX * (END - START)) / width;
    ticks.forEach((t) => {
      expect(t - START).toBeGreaterThanOrEqual(margin);
      expect(END - t).toBeGreaterThanOrEqual(margin);
    });
    // 20:00 est à 38 minutes du début, trop près à cette largeur.
    expect(hours(ticks)).not.toContain(20);
  });

  it("ne gradue rien sans largeur connue", () => {
    expect(hourTicks(START, END, 0, utcMinute)).toEqual([]);
  });

  it("suit l'heure de la maison", () => {
    // Fuseau à +5 h 30 : les heures pleines de la maison tombent à la demi-heure UTC.
    const shifted = (moment: Date) => (utcMinute(moment) + 330) % 1440;
    const ticks = hourTicks(START, END, 1700, shifted);
    ticks.forEach((t) => expect(shifted(new Date(t)) % 60).toBe(0));
  });
});
