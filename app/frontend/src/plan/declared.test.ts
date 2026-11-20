import { afterEach, describe, expect, it, vi } from "vitest";

import { declareLaunched, withdrawLaunched } from "./declared";

function mockApi(): string[] {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    calls.push(`${init?.method ?? "GET"} ${String(input)}`);
    return init?.method === "DELETE" ? new Response(null, { status: 204 }) : Response.json({}, { status: 201 });
  });
  return calls;
}

describe("« C'est lancé »", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("relance le calcul pour un cycle qui n'est pas le premier de la journée", async () => {
    // 20/11/2026 : seconde charge de sèche-linge déclarée ; les blocs prévus restaient ceux du
    // calcul d'avant jusqu'à l'heure suivante.
    const calls = mockApi();
    await declareLaunched("Sèche Linge #2");
    expect(calls).toEqual(["POST api/planning/launched", "POST api/planning/run"]);
  });

  it("ne relance pas le calcul pour le premier cycle : le plan n'en est pas changé", async () => {
    const calls = mockApi();
    await declareLaunched("Sèche Linge");
    await withdrawLaunched("Sèche Linge");
    expect(calls).toEqual(["POST api/planning/launched", "DELETE api/planning/launched/S%C3%A8che%20Linge"]);
  });

  it("relance aussi le calcul au retour en arrière d'un cycle suivant", async () => {
    const calls = mockApi();
    await withdrawLaunched("Lave-linge #3");
    expect(calls).toEqual(["DELETE api/planning/launched/Lave-linge%20%233", "POST api/planning/run"]);
  });

  it("ne lance pas de calcul si la déclaration échoue", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      calls.push(String(input));
      return new Response(null, { status: 500 });
    });
    await expect(declareLaunched("Sèche Linge #2")).rejects.toThrow();
    expect(calls).toEqual(["api/planning/launched"]);
  });
});
