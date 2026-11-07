// Heure de la maison : le fuseau de Home Assistant, pas celui du navigateur.

import { afterEach, describe, expect, it } from "vitest";

import { time } from "../plan/format";
import {
  homeDay,
  homeMidnight,
  homeTimeZone,
  hourOfDay,
  minuteOfDay,
  nextDay,
  setHomeTimeZone,
  zoned,
} from "./homeTime";

describe("heure de la maison", () => {
  afterEach(() => setHomeTimeZone(undefined));

  it("lit l'heure dans le fuseau de la maison, quel que soit celui du navigateur", () => {
    setHomeTimeZone("Pacific/Auckland"); // UTC+12 en juillet
    const moment = new Date("2026-07-01T00:30:00Z");

    expect(minuteOfDay(moment)).toBe(12 * 60 + 30);
    expect(hourOfDay(moment)).toBe(12.5);
    expect(homeDay(moment)).toBe("2026-07-01");
    expect(time("2026-07-01T00:30:00Z", "fr")).toBe("12:30");
  });

  it("un fuseau inconnu ou absent laisse celui du navigateur", () => {
    setHomeTimeZone("Not/A_Zone");
    expect(homeTimeZone()).toBeUndefined();
    expect(zoned({ hour: "2-digit" })).toEqual({ hour: "2-digit" });

    setHomeTimeZone("Europe/Paris");
    expect(zoned({ hour: "2-digit" })).toEqual({ hour: "2-digit", timeZone: "Europe/Paris" });
  });

  it("minuit de la maison, et des jours de 23 ou 25 h aux changements d'heure", () => {
    setHomeTimeZone("Europe/Paris");

    expect(homeMidnight("2026-07-01").toISOString()).toBe("2026-06-30T22:00:00.000Z");
    const spring = homeMidnight("2026-03-29");
    const autumn = homeMidnight("2026-10-25");
    expect(spring.toISOString()).toBe("2026-03-28T23:00:00.000Z");
    expect(autumn.toISOString()).toBe("2026-10-24T22:00:00.000Z");
    const hours = (day: string) => (homeMidnight(nextDay(day)).getTime() - homeMidnight(day).getTime()) / 3_600_000;
    expect(hours("2026-03-29")).toBe(23);
    expect(hours("2026-10-25")).toBe(25);
    expect(nextDay("2026-12-31")).toBe("2027-01-01");
  });
});
