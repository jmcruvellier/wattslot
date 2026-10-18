import { afterEach, describe, expect, it } from "vitest";

import { axisTick, setNumberLanguage } from "./format";

describe("graduations des axes", () => {
  afterEach(() => setNumberLanguage("en"));

  it("virgule décimale en français, unité accolée par une espace insécable", () => {
    setNumberLanguage("fr");
    expect(axisTick("kWh")(0.75)).toBe("0,75\u00a0kWh");
    expect(axisTick("kWh")(-0.3)).toBe("-0,3\u00a0kWh");
    expect(axisTick("%")(50)).toBe("50\u00a0%");
  });

  it("point décimal en anglais", () => {
    expect(axisTick("kWh")(1.5)).toBe("1.5\u00a0kWh");
  });
});
