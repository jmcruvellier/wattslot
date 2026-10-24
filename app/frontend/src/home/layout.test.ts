import { describe, expect, it } from "vitest";

import { translate } from "../i18n/translate";
import { buildGraph, type Graph } from "./graph";
import { layout, layoutInside, NODE_SPACING } from "./layout";
import { DEVICE_KINDS, type HomeModel } from "./types";

const t = (key: string, params?: Record<string, string | number>) => translate("fr", key, params);

// Maison d'essai : autant de capteurs que demandé par équipement.
function home(sensorCounts: number[]): HomeModel {
  return {
    devices: sensorCounts.map((sensors, index) => ({
      key: `device${index}`,
      kind: DEVICE_KINDS[index % DEVICE_KINDS.length],
      name: `Équipement ${index}`,
      capacity_kwh: null,
      sensors: Array.from({ length: sensors }, (_, sensor) => ({
        entity_id: `sensor.device${index}_${sensor}`,
        role: "PowerConsumed",
        resets_daily: false,
      })),
    })),
  };
}

// Deux objets se chevauchent si leurs centres sont plus proches que la largeur réservée d'un
// nœud (la hauteur, bien plus petite, rentre dans la marge).
function overlaps(graph: Graph, positions: Map<string, { x: number; y: number }>): [string, string] | null {
  const placed = graph.nodes.filter((node) => positions.has(node.id));
  for (let i = 0; i < placed.length; i++) {
    for (let j = i + 1; j < placed.length; j++) {
      const a = positions.get(placed[i].id)!;
      const b = positions.get(placed[j].id)!;
      if (Math.hypot(a.x - b.x, a.y - b.y) < NODE_SPACING - 20) return [placed[i].id, placed[j].id];
    }
  }
  return null;
}

describe("layout", () => {
  it("place tous les objets de l'ontologie, sans chevauchement", () => {
    for (const counts of [
      [2, 3, 2, 1], // maison simple
      [3, 3, 3, 3, 3, 3, 3, 3], // huit équipements bien remplis
      [12, 12, 12, 12], // branches denses : les rayons doivent s'élargir
      [0, 0, 0, 0, 0, 0], // équipements sans capteur
    ]) {
      const graph = buildGraph(home(counts), [], [], t);
      const positions = layout(graph);
      expect(graph.nodes.every((node) => positions.has(node.id))).toBe(true);
      expect(overlaps(graph, positions)).toBeNull();
    }
  });

  it("entoure l'élément double-cliqué de ses voisins, sans chevauchement", () => {
    const graph = buildGraph(home([6, 2]), [], [], t);
    for (const focus of ["device:device0", "sensor:device0:sensor.device0_1", "kind:WashingMachine"]) {
      const { positions, ids } = layoutInside(graph, focus);
      expect(ids.length).toBe(positions.size);
      expect(overlaps(graph, positions)).toBeNull();
      expect(positions.get(focus)).toEqual({ x: 0, y: 0 });
    }
  });
});
