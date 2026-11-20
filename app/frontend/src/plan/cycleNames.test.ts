import { describe, expect, it } from "vitest";

import { cycleNames } from "./cycleNames";
import type { Bar, DeviceStatus, TimelineRow } from "./types";

const bar = (start: number, end: number, kwh: number, more: Partial<Bar> = {}): Bar =>
  ({ start_hour: start, end_hour: end, energy_kwh: kwh, action: null, mode: null, ...more }) as Bar;

const row = (device: string, planned: Bar[], actual: Bar[]): TimelineRow =>
  ({ device, kind: "cycle", planned, actual }) as TimelineRow;

const status = (device: string, appliance: string, actualStart: number | null): DeviceStatus =>
  ({ device, appliance, status: actualStart === null ? "planned" : "on_time", actual_start_min: actualStart }) as DeviceStatus;

const names = (line: TimelineRow, statuses: DeviceStatus[] = []) => {
  const found = cycleNames(line, statuses);
  return { planned: line.planned.map((b) => found.get(b)), actual: line.actual.map((b) => found.get(b)) };
};

describe("nom des cycles dans la légende de la frise", () => {
  it("numérote deux lessives lancées sans demande, pas un réveil de veille", () => {
    // 20/11/2026 : lave-linge à 3 h et à 10 h, sans bloc prévu ; 0,06 kWh à 6 h 52.
    const washer = row("Lave Linge", [], [bar(3.02, 4.25, 0.37), bar(6.88, 7.12, 0.06), bar(10.05, 11.8, 0.43)]);

    expect(names(washer).actual).toEqual(["Lave Linge #1", undefined, "Lave Linge #2"]);
  });

  it("ne numérote pas un cycle seul dans la journée", () => {
    const planned = bar(10, 11.5, 1, { cycle: "Lave-linge" });
    expect(names(row("Lave-linge", [planned], [bar(10.08, 11.5, 1)]), [status("Lave-linge", "Lave-linge", 605)])).toEqual({
      planned: [undefined],
      actual: [undefined],
    });
    expect(names(row("Lave-linge", [], [bar(10, 11, 0.4), bar(12, 12.1, 0.01)])).actual).toEqual([undefined, undefined]);
  });

  it("donne au bloc prévu le numéro de son activité, et la suite aux cycles pas encore démarrés", () => {
    // Une lessive sans demande à 3 h, puis deux demandes : la première tourne à 10 h.
    const first = bar(10, 11.5, 0.4, { cycle: "Lave-linge" });
    const second = bar(16, 17.5, 0.4, { cycle: "Lave-linge #2" });
    const washer = row("Lave-linge", [first, second], [bar(3, 4.2, 0.4), bar(10.05, 10.3, 0.05)]);
    const statuses = [status("Lave-linge", "Lave-linge", 603), status("Lave-linge #2", "Lave-linge", null)];

    expect(names(washer, statuses)).toEqual({
      planned: ["Lave-linge #2", "Lave-linge #3"],
      // L'activité de 10 h 03 débute à peine : c'est un cycle, le bilan du serveur le dit.
      actual: ["Lave-linge #1", "Lave-linge #2"],
    });
  });

  it("compte la suite d'un cycle de la veille comme le premier de la journée", () => {
    const carried = bar(0, 1, 0.6, { carried: true });
    const evening = bar(22, 25, 3, { cycle: "Chauffe-eau" });
    // Pas encore de mesure : la suite de la veille, puis le cycle du soir.
    expect(names(row("Chauffe-eau", [carried, evening], [])).planned).toEqual(["Chauffe-eau #1", "Chauffe-eau #2"]);
    // Mesurée dès minuit : cette activité est la suite de la veille, pas un cycle de plus.
    expect(names(row("Chauffe-eau", [carried, evening], [bar(0, 0.9, 0.6)]))).toEqual({
      planned: ["Chauffe-eau #1", "Chauffe-eau #2"],
      actual: ["Chauffe-eau #1"],
    });
    // Seule dans la journée : pas de numéro.
    expect(names(row("Chauffe-eau", [carried], [bar(0, 0.9, 0.6)]))).toEqual({ planned: [undefined], actual: [undefined] });
  });

  it("ne numérote ni la batterie ni une durée à placer", () => {
    const pool = { ...row("Piscine", [bar(10, 12, 1), bar(14, 16, 1)], [bar(10, 12, 1), bar(14, 16, 1)]), kind: "runtime" };
    expect(cycleNames(pool as TimelineRow, []).size).toBe(0);
  });
});
