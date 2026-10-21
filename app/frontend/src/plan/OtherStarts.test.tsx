// Autres départs proposés par le plan : choisir l'un d'eux, ou revenir au choix du calcul.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import OtherStarts from "./OtherStarts";

type Call = { url: string; method: string; body: unknown };

function mockApi(): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body ? (JSON.parse(String(init.body)) as unknown) : null,
    });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    return Response.json({});
  });
  return calls;
}

const OTHERS = [
  { start_min: 1200, cost_eur_delta: -0.099, import_kwh_delta: -0.732 },
  { start_min: 1140, cost_eur_delta: 0.05, import_kwh_delta: 0.2 },
];

describe("autres départs", () => {
  beforeEach(() => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("choisit un autre départ, puis relance le calcul", async () => {
    const calls = mockApi();
    const onChanged = vi.fn();
    render(
      <I18nProvider>
        <OtherStarts device="Chauffe-Eau" alternatives={OTHERS} chosen={false} onChanged={onChanged} />
      </I18nProvider>,
    );

    expect(screen.getByText("Autres départs possibles :")).toBeInTheDocument();
    const first = screen.getByRole("button", { name: /Choisir le départ de 20h00 \(-0,10\s€, -0,7 kWh/ });
    expect(first).toHaveTextContent(/20h00 · -0,10\s€/);
    expect(screen.queryByRole("button", { name: "Revenir au choix du calcul" })).toBeNull();
    await userEvent.click(first);

    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["POST", "api/planning/choices"],
      ["POST", "api/planning/run"],
    ]);
    expect(calls[0].body).toEqual({ device: "Chauffe-Eau", start_min: 1200 });
    expect(onChanged).toHaveBeenCalled();
  });

  it("rend un départ choisi au calcul", async () => {
    const calls = mockApi();
    render(
      <I18nProvider>
        <OtherStarts device="Chauffe-Eau" alternatives={[]} chosen onChanged={vi.fn()} />
      </I18nProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Revenir au choix du calcul" }));

    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["DELETE", "api/planning/choices/Chauffe-Eau"],
      ["POST", "api/planning/run"],
    ]);
  });

  it("ne montre rien sans autre départ ni choix", () => {
    const { container } = render(
      <I18nProvider>
        <OtherStarts device="Chauffe-Eau" alternatives={[]} chosen={false} onChanged={vi.fn()} />
      </I18nProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
