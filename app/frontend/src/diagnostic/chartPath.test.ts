import { describe, expect, it } from "vitest";

import { smoothPath } from "./chartPath";

/** Points de contrôle et points d'arrivée des « C » du chemin, en [x, y]. */
function curves(path: string): number[][][] {
  return path
    .split("C")
    .slice(1)
    .map((part) => part.trim().split(" ").map((pair) => pair.split(",").map(Number)));
}

describe("smoothPath", () => {
  it("passe par chaque relevé", () => {
    const path = smoothPath([
      [0, 50],
      [10, 20],
      [20, 80],
    ]);
    expect(path.startsWith("M0.0,50.0")).toBe(true);
    expect(curves(path).map((curve) => curve[2])).toEqual([
      [10, 20],
      [20, 80],
    ]);
  });

  it("n'invente pas de pic : les points de contrôle restent entre les relevés voisins", () => {
    const points: [number, number][] = [
      [0, 100],
      [10, 100],
      [20, 20],
      [30, 100],
      [40, 95],
      [50, 100],
    ];
    curves(smoothPath(points)).forEach((curve, index) => {
      const low = Math.min(points[index][1], points[index + 1][1]);
      const high = Math.max(points[index][1], points[index + 1][1]);
      for (const [, y] of curve) {
        expect(y).toBeGreaterThanOrEqual(low);
        expect(y).toBeLessThanOrEqual(high);
      }
    });
  });

  it("garde un plat plat, et un point seul en simple départ", () => {
    for (const [, y] of curves(smoothPath([[0, 40], [10, 40], [20, 40]])).flat()) expect(y).toBe(40);
    expect(smoothPath([[5, 7]])).toBe("M5.0,7.0");
    expect(smoothPath([])).toBe("");
  });
});
