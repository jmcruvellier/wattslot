import { describe, expect, it } from "vitest";

import { laneOffset, linkShapes, stubPx, turnsBack } from "./timelineLinks";
import type { Bar, Timeline, TimelineLink, TimelineRow } from "./types";

const bar = (start: number, end: number): Bar =>
  ({ start_hour: start, end_hour: end, energy_kwh: 1, action: null, mode: null }) as Bar;

const row = (device: string, planned: Bar[] = [], actual: Bar[] = []): TimelineRow =>
  ({ device, kind: "cycle", planned, actual }) as TimelineRow;

const link = (from: number, to: number, started = true, target = "Sèche-linge"): TimelineLink => ({
  source: "Lave-linge",
  target,
  from_hour: from,
  to_hour: to,
  started,
});

const timeline = (rows: TimelineRow[], links: TimelineLink[]): Timeline => ({ rows, links }) as Timeline;

describe("tracé des liaisons de la frise", () => {
  it("descend une seule fois, au milieu de l'espace libre commun aux deux lignes", () => {
    // 20/11/2026 : lessives de 3 h à 4 h 15 et de 10 h à 11 h 45 (réveil de veille à 6 h 54),
    // séchages de 10 h à 12 h 30 et de 12 h 45 à 15 h 30.
    const shapes = linkShapes(
      timeline(
        [
          row("Lave-linge", [], [bar(3, 4.25), bar(6.9, 7.1), bar(10, 11.75)]),
          row("Sèche-linge", [], [bar(10, 12.5), bar(12.75, 15.5)]),
        ],
        [link(11.75, 12.75), link(4.25, 10)],
      ),
    ).get("Sèche-linge")!;

    // Première liaison : libre de 4 h 15 au réveil de 6 h 54 sur la ligne du dessus. Seconde :
    // libre de 12 h 30 (fin du premier séchage) à 12 h 45 sur celle du dessous.
    expect(shapes.map((shape) => [shape.from, shape.to, shape.skip])).toEqual([
      [4.25, 10, 0],
      [11.75, 12.75, 0],
    ]);
    expect(shapes[0].via).toBeCloseTo((4.25 + 6.9) / 2);
    expect(shapes[1].via).toBeCloseTo((12.5 + 12.75) / 2);
  });

  it("trace un simple trait vertical entre deux cycles qui se touchent", () => {
    // Lessive prévue jusqu'à 19 h, séchage prévu à 19 h.
    const shapes = linkShapes(
      timeline([row("Lave-linge", [bar(17, 19)]), row("Sèche-linge", [bar(19, 21)])], [link(19, 19, false)]),
    ).get("Sèche-linge")!;

    expect(shapes.map((shape) => [shape.via, shape.started])).toEqual([[19, false]]);
  });

  it("descend avant le crochet d'un bloc prévu qui couvre l'arrivée", () => {
    // Séchage prévu de 13 h à 15 h, lancé à 14 h : la descente reste avant 13 h.
    const shapes = linkShapes(
      timeline(
        [row("Lave-linge", [], [bar(10, 12)]), row("Sèche-linge", [bar(13, 15)], [bar(14, 16)])],
        [link(12, 14)],
      ),
    ).get("Sèche-linge")!;

    expect(shapes[0].via).toBeCloseTo(12.5);
  });

  it("passe par la marge entre les pistes sans espace libre commun, la plus tardive au-dessus", () => {
    // Sur la ligne du dessus, un bloc commence (5 h, 6 h 30) avant que celle du dessous soit
    // libre (7 h, 9 h) : pas de descente possible sans toucher un bloc.
    const shapes = linkShapes(
      timeline(
        [
          row("Lave-linge", [], [bar(2, 4), bar(5, 6), bar(6.5, 7.5)]),
          row("Sèche-linge", [], [bar(3, 7), bar(8, 9), bar(10, 11)]),
        ],
        [link(6, 10, false), link(4, 8)],
      ),
    ).get("Sèche-linge")!;

    expect(shapes.map((shape) => [shape.from, shape.via, shape.lane, shape.lanes, shape.started])).toEqual([
      [4, null, 0, 2, true],
      [6, null, 1, 2, false],
    ]);
    // Le couloir du dessus est au-dessus de la piste (négatif), celui du dessous dedans, et
    // tous deux dans la marge libre de 0,4 rem de part et d'autre.
    expect(laneOffset(shapes[0])).toBeGreaterThan(0);
    expect(laneOffset(shapes[0])).toBeLessThan(0.4);
    expect(laneOffset(shapes[1])).toBeLessThan(0);
    expect(laneOffset(shapes[1])).toBeGreaterThan(-0.4);
    // Sortie et entrée du tracé de repli : 8 pixels, moins quand un autre bloc est tout près
    // (piste de 960 pixels, 40 par heure : une demi-heure libre après 6 h, soit 20 pixels).
    expect(shapes.map((shape) => [shape.roomAfter, shape.roomBefore])).toEqual([
      [1, 1],
      [0.5, 1],
    ]);
    expect(shapes.map((shape) => stubPx(shape, 960))).toEqual([8, 8]);
    expect(stubPx({ ...shapes[1], roomAfter: 0.25 }, 960)).toBe(5);
    expect(stubPx({ ...shapes[1], roomAfter: 0 }, 960)).toBe(2);
    expect(stubPx(shapes[1], 0)).toBe(8); // largeur inconnue : la longueur ordinaire
    expect(turnsBack(shapes[0], 960)).toBe(false);
    expect(turnsBack({ ...shapes[0], to: 4.1 }, 960)).toBe(true);
  });

  it("compte les lignes entre les deux, et ignore une liaison sans ses deux lignes dans l'ordre", () => {
    const rows = [row("Lave-linge"), row("Sèche-linge"), row("Repassage")];
    const found = linkShapes(
      timeline(rows, [
        link(8, 10, true, "Repassage"),
        link(8, 9, true, "Absent"),
        { ...link(8, 9), source: "Repassage", target: "Lave-linge" },
      ]),
    );

    expect([...found.keys()]).toEqual(["Repassage"]);
    expect(found.get("Repassage")?.[0].skip).toBe(1);
  });

  it("ne trace rien sans liaison (plan d'une version précédente)", () => {
    expect(linkShapes({ rows: [row("Lave-linge")] } as Timeline).size).toBe(0);
  });
});
