import { describe, expect, it } from "vitest";

import { freeSpan } from "./timelineSpan";
import type { Bar } from "./types";

const bar = (start_hour: number, end_hour: number): Bar =>
  ({ start_hour, end_hour, energy_kwh: 1, action: null, mode: null }) as Bar;

describe("place libre d'un bloc", () => {
  it("bloc seul : tout le bloc", () => {
    expect(freeSpan([bar(9, 12)], 0)).toEqual([9, 12]);
  });

  it("la plus grande partie que les blocs dessinés après lui ne recouvrent pas", () => {
    const items = [bar(9, 15), bar(10, 10.5), bar(12, 14)];
    expect(freeSpan(items, 0)).toEqual([10.5, 12]);
  });

  it("bloc entièrement recouvert : aucune place", () => {
    expect(freeSpan([bar(9, 10), bar(8, 11)], 0)).toEqual([9, 9]);
  });

  it("ignore les blocs dessinés avant lui", () => {
    expect(freeSpan([bar(10, 11), bar(9, 15)], 1)).toEqual([9, 15]);
  });
});
