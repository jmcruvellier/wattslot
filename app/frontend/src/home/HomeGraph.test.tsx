import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import HomeGraph from "./HomeGraph";

// Graphe de la maison : sur téléphone, la liste remplace le dessin. Sur grand écran, toute
// l'ontologie est visible d'un coup — bibliothèque, types, équipements, capteurs — et chaque nœud
// porte ses poignées d'attache (source et cible, aux quatre côtés) : React Flow les attend pour
// dessiner les liaisons — un nœud sans poignée les fait disparaître en silence.

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

  it("montre toute l'ontologie d'un coup, et ouvre la fiche de l'élément cliqué", async () => {
    // Écran large : le dessin remplace la liste, avec tous les objets du modèle.
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("max-width"), media: query }));
    mockHomeApi();

    const { container } = render(
      <I18nProvider>
        <HomeGraph />
      </I18nProvider>,
    );

    // Le type de la bibliothèque, l'équipement et son capteur sont tous sur le dessin, sans fiche
    // ouverte d'office.
    await screen.findByRole("figure", { name: "Ma maison en graphe" });
    // Le type de la bibliothèque, l'équipement (même nom) et son capteur sont sur le dessin,
    // sans fiche ouverte d'office.
    await screen.findAllByText("Lave-linge");
    expect(screen.getAllByText("Lave-linge").length).toBe(2); // le type et l'équipement
    expect(screen.getByText("sensor.washer_power")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Lave-linge" })).toBeNull();
    const nodes = container.querySelectorAll(".react-flow__node");
    const handles = container.querySelectorAll(".react-flow__handle");
    // Les liaisons ne se dessinent que sur les poignées : huit par nœud, deux par côté.
    expect(nodes.length).toBe(3);
    expect(handles.length).toBe(nodes.length * 8);

    // Un clic sur l'équipement ouvre sa fiche, avec ses propriétés et son anomalie.
    fireEvent.click(container.querySelector('[data-id="device:washer"]')!);
    const details = await screen.findByRole("region", { name: "Lave-linge" });
    expect(details).toHaveTextContent("Capteurs");
    expect(details.querySelector(".issue")).not.toBeNull();

    // La fiche se ferme par son bouton.
    fireEvent.click(screen.getByRole("button", { name: "Fermer" }));
    expect(screen.queryByRole("region", { name: "Lave-linge" })).toBeNull();
  });
});
