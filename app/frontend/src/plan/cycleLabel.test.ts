import { describe, expect, it } from "vitest";

import { cycleLabels } from "./cycleLabel";

describe("nom affiché des cycles d'une journée", () => {
  it("numérote le premier cycle dès que l'équipement en a plusieurs", () => {
    const labels = cycleLabels(["Sèche-linge", "Sèche-linge #2", "Lave-linge", "Sèche-linge #3"]);

    expect(labels.get("Sèche-linge")).toBe("Sèche-linge #1");
    expect(labels.get("Sèche-linge #2")).toBe("Sèche-linge #2");
    expect(labels.get("Sèche-linge #3")).toBe("Sèche-linge #3");
    // Un seul cycle : pas de numéro.
    expect(labels.get("Lave-linge")).toBe("Lave-linge");
  });

  it("ne compte pas deux fois le même cycle, et ne numérote pas un second cycle resté seul", () => {
    expect(cycleLabels(["Lave-linge", "Lave-linge"]).get("Lave-linge")).toBe("Lave-linge");
    expect(cycleLabels(["Lave-linge #2"]).get("Lave-linge #2")).toBe("Lave-linge #2");
  });
});
