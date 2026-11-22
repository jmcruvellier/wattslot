import { describe, expect, it } from "vitest";

import { pendingFinish, pendingLatest } from "./pendingLatest";

describe("pendingLatest", () => {
  const request = (device: string, latest: string | null, extra: object = {}) => ({
    device,
    latest,
    status: "open",
    launched_on: null,
    ...extra,
  });

  it("garde la demande la plus récente de chaque appareil, pas encore lancée", () => {
    const found = pendingLatest([
      request("washer", "2026-10-19"), // la plus récente : en tête de liste
      request("washer", "2026-10-18"),
      request("dryer", null),
      request("heater", "2026-10-18", { launched_on: "2026-10-17" }),
      request("dishwasher", "2026-10-18", { status: "done" }),
    ]);

    expect(found).toEqual({ washer: "2026-10-19", dryer: null });
  });

  it("donne l'heure limite de la même demande, ou aucune", () => {
    const found = pendingFinish([
      request("washer", "2026-10-19", { finish_hour: 12 }),
      request("washer", "2026-10-18", { finish_hour: 18 }),
      request("dryer", null),
      request("heater", null, { finish_hour: 7, launched_on: "2026-10-17" }),
    ]);

    expect(found).toEqual({ washer: 12, dryer: null });
  });
});
