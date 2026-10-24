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
    // Le bouton « centrer » des commandes est bien là, sous les boutons de zoom : il recadre
    // avec la bande de recherche réservée (options passées aux commandes).
    expect(container.querySelector(".react-flow__controls-fitview")).not.toBeNull();
    expect(container.querySelectorAll(".react-flow__controls-button").length).toBe(3); // +, -, centrer
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

    // Un double-clic entre dans l'élément : lui au centre, ses voisins autour, et « Retour »
    // pour revenir à la vue d'ensemble.
    fireEvent.doubleClick(container.querySelector('[data-id="sensor:washer:sensor.washer_power"]')!);
    await screen.findByRole("region", { name: "sensor.washer_power" });
    expect(container.querySelectorAll(".react-flow__node").length).toBe(2); // le capteur et son équipement
    fireEvent.click(screen.getByRole("button", { name: /Retour/ }));
    await screen.findAllByText("Lave-linge");
    expect(container.querySelectorAll(".react-flow__node").length).toBe(3);
  });

  it("recherche les éléments de la vue et recadre le dessin sur eux", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("max-width"), media: query }));
    mockHomeApi();

    const { container } = render(
      <I18nProvider>
        <HomeGraph />
      </I18nProvider>,
    );
    await screen.findByRole("figure", { name: "Ma maison en graphe" });

    // La recherche ne trouve que le type et l'équipement « Lave-linge » ; le capteur s'efface.
    const input = screen.getByRole("textbox", { name: "Rechercher un élément…" });
    fireEvent.change(input, { target: { value: "lave" } });
    expect(container.querySelector('[data-id="device:washer"]')?.className).toContain("graph-hit");
    expect(container.querySelector('[data-id="kind:WashingMachine"]')?.className).toContain("graph-hit");
    expect(container.querySelector('[data-id="sensor:washer:sensor.washer_power"]')?.className).toContain("graph-dim");
    expect(screen.queryByRole("status", { name: "" })).toBeNull();

    // Un texte sans résultat le dit ; effacer la recherche rend tous les objets.
    fireEvent.change(input, { target: { value: "zzz" } });
    await screen.findByRole("status");
    expect(container.querySelectorAll(".graph-dim").length).toBe(3);
    fireEvent.click(screen.getByRole("button", { name: "Effacer la recherche" }));
    expect(container.querySelectorAll(".graph-dim").length).toBe(0);
    expect((screen.getByRole("textbox", { name: "Rechercher un élément…" }) as HTMLInputElement).value).toBe("");
  });

  it("passe le canevas en plein écran, refermé par Échap ou sa croix", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: !query.includes("max-width"), media: query }));
    mockHomeApi();

    render(
      <I18nProvider>
        <HomeGraph />
      </I18nProvider>,
    );
    await screen.findByRole("figure", { name: "Ma maison en graphe" });

    // Plein écran : le canevas couvre la page entière (portail vers le corps du document).
    fireEvent.click(screen.getByRole("button", { name: "Plein écran" }));
    const fullscreen = document.querySelector(".graph-fullscreen");
    expect(fullscreen).not.toBeNull();
    expect(document.body.contains(fullscreen!)).toBe(true);

    // Échap referme la fiche d'abord, puis le plein écran (le canevas est dans le corps).
    fireEvent.click(document.querySelector('[data-id="device:washer"]')!);
    await screen.findByRole("region", { name: "Lave-linge" });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Lave-linge" })).toBeNull();
    expect(document.querySelector(".graph-fullscreen")).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelector(".graph-fullscreen")).toBeNull();

    // La croix referme aussi le plein écran.
    fireEvent.click(screen.getByRole("button", { name: "Plein écran" }));
    expect(document.querySelector(".graph-fullscreen")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Quitter le plein écran" }));
    expect(document.querySelector(".graph-fullscreen")).toBeNull();
  });
});
