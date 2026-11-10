import { describe, expect, it } from "vitest";

import { buildDraft, MANUAL_PREFIX, mergeDraft, slug, toModel } from "./draft";
import type { DeviceProposal, HomeModel } from "./types";

const PROPOSALS: DeviceProposal[] = [
  {
    key: "battery-1",
    kind: "Battery",
    name: "Battery",
    capacity_kwh: null,
    issues: [{ code: "battery_capacity_missing", params: {} }],
    sensors: [
      {
        entity_id: "sensor.battery_soc",
        role: "StateOfCharge",
        name: null,
        unit: "%",
        resets_daily: false,
        excluded: false,
        issues: [],
      },
    ],
  },
  {
    key: "OtherLoad-tv",
    kind: "OtherLoad",
    name: "Salon TV",
    capacity_kwh: null,
    issues: [],
    sensors: [
      {
        entity_id: "sensor.tv_energy",
        role: "EnergyConsumed",
        name: null,
        unit: "kWh",
        resets_daily: false,
        excluded: false,
        issues: [],
      },
    ],
  },
];

const EMPTY: HomeModel = { devices: [] };

describe("buildDraft", () => {
  it("retient toutes les propositions à la première validation", () => {
    expect(buildDraft(PROPOSALS, EMPTY).map((d) => d.included)).toEqual([true, true]);
  });

  it("reprend les choix enregistrés et décoche les nouveautés", () => {
    const saved: HomeModel = {
      devices: [
        {
          key: "battery-1",
          kind: "Battery",
          name: "Batterie du garage",
          capacity_kwh: 5.12,
          sensors: [],
        },
      ],
    };

    const draft = buildDraft(PROPOSALS, saved);

    expect(draft[0]).toMatchObject({ included: true, name: "Batterie du garage", capacityKwh: 5.12 });
    expect(draft[1].included).toBe(false);
  });

  it("garde un équipement enregistré qui n'est plus proposé", () => {
    const saved: HomeModel = {
      devices: [{ key: "old", kind: "Dryer", name: "Ancien", capacity_kwh: null, sensors: [] }],
    };

    const draft = buildDraft(PROPOSALS, saved);

    expect(draft.at(-1)).toMatchObject({ key: "old", included: true });
    expect(draft.at(-1)?.issues[0].code).toBe("not_proposed");
  });
});

describe("mergeDraft", () => {
  it("garde les choix en cours quand les propositions sont relues", () => {
    const previous = buildDraft(PROPOSALS, EMPTY).map((d) => ({ ...d, included: false, name: "X" }));

    const merged = mergeDraft(previous, buildDraft(PROPOSALS, EMPTY));

    expect(merged.map((d) => [d.included, d.name])).toEqual([
      [false, "X"],
      [false, "X"],
    ]);
  });
});

describe("toModel", () => {
  it("n'enregistre que les équipements retenus, capacité des seules batteries", () => {
    const draft = buildDraft(PROPOSALS, EMPTY).map((d) =>
      d.key === "OtherLoad-tv" ? { ...d, included: false } : { ...d, capacityKwh: 5 },
    );

    expect(toModel(draft)).toEqual({
      devices: [
        {
          key: "battery-1",
          kind: "Battery",
          custom_type: null,
          phase: null,
          name: "Battery",
          capacity_kwh: 5,
          sensors: [{ entity_id: "sensor.battery_soc", role: "StateOfCharge", resets_daily: false }],
        },
      ],
    });
  });
});

describe("phase", () => {
  const saved: HomeModel = {
    devices: [
      { key: "battery-1", kind: "Battery", name: "Battery", capacity_kwh: 5, phase: "PhaseL2", sensors: [] },
      { key: "grid", kind: "GridConnection", name: "Grid", capacity_kwh: null, phase: "PhaseL1", sensors: [] },
    ],
  };

  it("garde la phase enregistrée, sauf celle du raccordement au réseau", () => {
    const draft = buildDraft(PROPOSALS, saved);

    expect(draft.find((d) => d.key === "battery-1")?.phase).toBe("PhaseL2");
    const phases = Object.fromEntries(toModel(draft).devices.map((d) => [d.key, d.phase]));
    expect(phases).toEqual({ "battery-1": "PhaseL2", grid: null });
  });

  it("garde la phase choisie quand les propositions sont relues", () => {
    const edited = buildDraft(PROPOSALS, saved).map((d) => ({ ...d, phase: "PhaseL3" as const }));

    expect(mergeDraft(edited, buildDraft(PROPOSALS, saved)).every((d) => d.phase === "PhaseL3")).toBe(true);
  });
});

describe("capteurs par phase du réseau", () => {
  const grid = (sensors: HomeModel["devices"][number]["sensors"]): HomeModel => ({
    devices: [{ key: "grid", kind: "GridConnection", name: "Grid", capacity_kwh: null, sensors }],
  });
  const proposal: DeviceProposal = {
    key: "grid",
    kind: "GridConnection",
    name: "Grid",
    capacity_kwh: null,
    issues: [],
    sensors: [
      { entity_id: "sensor.import", role: "EnergyImported", name: null, unit: "kWh", resets_daily: false, excluded: false, issues: [] },
    ],
  };

  it("garde les capteurs par phase ajoutés à la main, que HA ne propose pas", () => {
    const saved = grid([
      { entity_id: "sensor.import", role: "EnergyImported", resets_daily: false },
      { entity_id: "sensor.import_l2", role: "EnergyImported", resets_daily: false, phase: "PhaseL2" },
    ]);

    const model = toModel(buildDraft([proposal], saved));

    expect(model.devices[0].sensors).toEqual([
      { entity_id: "sensor.import", role: "EnergyImported", resets_daily: false },
      { entity_id: "sensor.import_l2", role: "EnergyImported", resets_daily: false, phase: "PhaseL2" },
    ]);
  });

  it("n'enregistre pas de phase pour le capteur d'un autre équipement", () => {
    const draft = buildDraft([proposal], grid([])).map((d) => ({
      ...d,
      kind: "OtherLoad" as const,
      sensors: d.sensors.map((sensor) => ({ ...sensor, included: true, phase: "PhaseL1" as const })),
    }));

    expect(toModel(draft).devices[0].sensors[0]).not.toHaveProperty("phase");
  });
});

describe("capteurs", () => {
  const withCost: DeviceProposal = {
    key: "grid",
    kind: "GridConnection",
    name: "Grid",
    capacity_kwh: null,
    issues: [],
    sensors: [
      {
        entity_id: "sensor.cost",
        role: "EnergyImported",
        name: null,
        unit: "Wh",
        resets_daily: false,
        excluded: true,
        issues: [{ code: "name_suggests_cost", params: { entity: "sensor.cost" } }],
      },
      {
        entity_id: "sensor.peak",
        role: "EnergyImported",
        name: null,
        unit: "kWh",
        resets_daily: false,
        excluded: false,
        issues: [],
      },
    ],
  };

  it("un capteur proposé exclu arrive décoché et n'est pas enregistré", () => {
    const draft = buildDraft([withCost], EMPTY);

    expect(draft[0].sensors.map((s) => s.included)).toEqual([false, true]);
    expect(toModel(draft).devices[0].sensors.map((s) => s.entity_id)).toEqual(["sensor.peak"]);
  });

  it("reprend les capteurs enregistrés, même un capteur proposé exclu", () => {
    const saved: HomeModel = {
      devices: [
        {
          key: "grid",
          kind: "GridConnection",
          name: "Réseau",
          capacity_kwh: null,
          sensors: [{ entity_id: "sensor.cost", role: "EnergyImported", resets_daily: false }],
        },
      ],
    };

    expect(buildDraft([withCost], saved)[0].sensors.map((s) => s.included)).toEqual([true, false]);
  });

  it("garde le choix d'un capteur quand les propositions sont relues", () => {
    const previous = buildDraft([withCost], EMPTY).map((device) => ({
      ...device,
      sensors: device.sensors.map((sensor) => ({ ...sensor, included: true })),
    }));

    const merged = mergeDraft(previous, buildDraft([withCost], EMPTY));

    expect(merged[0].sensors.map((s) => s.included)).toEqual([true, true]);
  });
});

describe("capacité de la batterie", () => {
  it("reprend la capacité proposée et l'entité dont elle vient", () => {
    const proposal: DeviceProposal = {
      ...PROPOSALS[0],
      capacity_kwh: 5.12,
      capacity_source: "sensor.battery_total_energy",
      issues: [],
    };

    expect(buildDraft([proposal], EMPTY)[0]).toMatchObject({
      capacityKwh: 5.12,
      capacitySource: "sensor.battery_total_energy",
    });
  });
});

describe("équipements ajoutés à la main", () => {
  it("tire une clé lisible d'un nom", () => {
    expect(slug("Pompe à chaleur — Garage")).toBe("pompe-a-chaleur-garage");
  });

  it("ne signale pas comme disparu un équipement ajouté à la main", () => {
    const saved: HomeModel = {
      devices: [
        { key: `${MANUAL_PREFIX}pac`, kind: "OtherLoad", name: "PAC", capacity_kwh: null, sensors: [] },
        { key: "old", kind: "Dryer", name: "Ancien", capacity_kwh: null, sensors: [] },
      ],
    };

    const issues = buildDraft([], saved).map((device) => device.issues.map((issue) => issue.code));

    expect(issues).toEqual([[], ["not_proposed"]]);
  });
});
