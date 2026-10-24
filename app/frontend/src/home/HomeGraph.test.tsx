import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import HomeGraph from "./HomeGraph";

// Graphe de la maison : sur téléphone, la liste remplace le dessin. Sur grand écran, l'explorateur
// d'ontologie met un élément au centre, ses voisins autour, et chaque nœud porte ses poignées
// d'attache (source et cible, aux quatre côtés) : React Flow les attend pour dessiner les
// liaisons — un nœud sans poignée les fait disparaître en silence.

function mockHomeApi() {
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
}

describe("HomeGraph", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    // Le canevas de React Flow n'existe pas dans jsdom : observateur de redimensionnement muet.
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.stubGlobal(
      "DOMMatrixReadOnly",
      class {
        m22 = 1;
        scale() {
          return this;
        }
        translate() {
          return this;
        }
        multiply() {
          return this;
        }
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("montre sur téléphone la liste des équipements, de leurs capteurs et de leurs anomalies", async () => {
    // Écran étroit : la liste remplace le graphe.
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width"), media: query }));
    mockHomeApi();

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

  it("explore l'ontologie : premier équipement au centre, fiche ouverte, voisin puis retour", async () => {
    // Écran large : l'explorateur d'ontologie remplace la liste.
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("max-width"), media: query }));
    mockHomeApi();

    const { container } = render(
      <I18nProvider>
        <HomeGraph />
      </I18nProvider>,
    );

    // Le premier équipement est au centre, sa fiche ouverte, ses voisins autour.
    await screen.findByRole("figure", { name: "Ma maison en graphe" });
    const details = await screen.findByRole("region", { name: "Lave-linge" });
    expect(details.querySelector(".issue")).not.toBeNull();
    const nodes = container.querySelectorAll(".react-flow__node");
    const handles = container.querySelectorAll(".react-flow__handle");
    // Les liaisons ne se dessinent que sur les poignées : huit par nœud, deux par côté.
    expect(nodes.length).toBeGreaterThan(1);
    expect(handles.length).toBe(nodes.length * 8);

    // Un clic sur un voisin le place au centre et ouvre sa fiche.
    const sensor = container.querySelector('[data-id="sensor:washer:sensor.washer_power"]');
    expect(sensor).not.toBeNull();
    fireEvent.click(sensor!);
    const sensorDetails = await screen.findByRole("region", { name: "sensor.washer_power" });
    expect(sensorDetails).toHaveTextContent("Rôle");

    // « Retour » revient à l'élément précédent, dont la fiche s'ouvre.
    fireEvent.click(screen.getByRole("button", { name: /Retour/ }));
    await screen.findByRole("region", { name: "Lave-linge" });
  });
});
