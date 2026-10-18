import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import HomeGraph from "./HomeGraph";

describe("HomeGraph", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    // Écran étroit : la liste remplace le graphe.
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width"), media: query }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("montre sur téléphone la liste des équipements, de leurs capteurs et de leurs anomalies", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home") {
        return Response.json({
          devices: [
            {
              key: "washer",
              kind: "WashingMachine",
              name: "Lave-linge",
              capacity_kwh: null,
              sensors: [{ entity_id: "sensor.washer_power", role: "PowerConsumed", resets_daily: false }],
            },
          ],
        });
      }
      if (url === "api/home/types") return Response.json({ parents: [], types: [], library: [] });
      if (url === "api/configuration") return Response.json({ version: 1, devices: [] });
      if (url === "api/configuration/validate") {
        return Response.json({ issues: [{ code: "automation_not_available", device: "washer", params: {} }] });
      }
      return new Response(null, { status: 404 });
    });

    render(
      <I18nProvider>
        <HomeGraph />
      </I18nProvider>,
    );

    const washer = await screen.findByRole("region", { name: "Lave-linge" });
    expect(washer).toHaveTextContent("Lave-linge");
    expect(screen.getByText("sensor.washer_power")).toBeInTheDocument();
    expect(washer.querySelector(".issue")).not.toBeNull();
  });
});
