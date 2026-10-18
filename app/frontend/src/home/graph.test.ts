import { describe, expect, it } from "vitest";

import { translate } from "../i18n/translate";
import { buildGraph } from "./graph";
import type { DeviceType, HomeModel } from "./types";

const t = (key: string, params?: Record<string, string | number>) => translate("fr", key, params);

const PUMP: DeviceType = { key: "pac", name: "Pompe à chaleur", parent: "OtherLoad" };
const HOME: HomeModel = {
  devices: [
    {
      key: "washer",
      kind: "WashingMachine",
      name: "Lave-linge",
      capacity_kwh: null,
      sensors: [{ entity_id: "sensor.washer_power", role: "PowerConsumed", resets_daily: false }],
    },
    { key: "pac", kind: "OtherLoad", custom_type: "pac", name: "PAC du garage", capacity_kwh: null, sensors: [] },
  ],
};

describe("buildGraph", () => {
  it("relie les capteurs aux équipements, les équipements à leur type, les types à leur parent", () => {
    const graph = buildGraph(HOME, [PUMP], [], t);

    expect(graph.nodes.map((n) => [n.id, n.column])).toEqual([
      ["kind:WashingMachine", 0],
      ["kind:OtherLoad", 0],
      ["type:pac", 1],
      ["device:washer", 2],
      ["sensor:washer:sensor.washer_power", 3],
      ["device:pac", 2],
    ]);
    expect(graph.edges.map((e) => [e.source, e.target, e.label])).toEqual([
      ["type:pac", "kind:OtherLoad", "sous-type de"],
      ["device:washer", "kind:WashingMachine", "est un"],
      ["device:washer", "sensor:washer:sensor.washer_power", "capteur"],
      ["device:pac", "type:pac", "est un"],
    ]);
    const pac = graph.nodes.find((n) => n.id === "device:pac");
    expect(pac?.details).toContainEqual(["Type", "Pompe à chaleur"]);
    expect(pac?.row).toBe(1); // deuxième équipement de sa colonne
  });

  it("porte les anomalies de la configuration sur l'équipement, traduites", () => {
    const graph = buildGraph(HOME, [PUMP], [{ code: "behavior_not_allowed", device: "washer", params: { behavior: "x", kind: "y", allowed: "z" } }], t);

    const washer = graph.nodes.find((n) => n.id === "device:washer");
    expect(washer?.issues).toHaveLength(1);
    expect(washer?.issues[0]).toContain("Lave-linge");
  });
});
