import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import type { DeviceType, DeviceTypes } from "../home/types";
import LibraryScreen from "./LibraryScreen";

const PUMP: DeviceType = { key: "pompe-a-chaleur", name: "Pompe à chaleur", parent: "OtherLoad" };

function types(own: DeviceType[]): DeviceTypes {
  return {
    parents: ["SolarInstallation", "Battery", "WashingMachine", "OtherLoad"],
    types: own,
    library: [
      { kind: "WashingMachine", behaviors: ["CycleBehavior", "UncontrolledBehavior"], roles: ["PowerConsumed", "EnergyConsumed"], subtypes: true },
      { kind: "GridConnection", behaviors: ["GridBehavior"], roles: ["EnergyImported", "EnergyExported"], subtypes: false },
    ],
  };
}

function renderScreen() {
  return render(
    <I18nProvider>
      <LibraryScreen />
    </I18nProvider>,
  );
}

describe("LibraryScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("présente les types de la bibliothèque, leurs comportements et leurs capteurs", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json(types([])));
    renderScreen();

    const washer = await screen.findByRole("row", { name: /Lave-linge/ });
    expect(washer).toHaveTextContent("Cycle à démarrer, Consommation seulement suivie");
    expect(washer).toHaveTextContent("Puissance consommée, Énergie consommée");
    expect(screen.getByText("Aucun type à vous pour l'instant.")).toBeInTheDocument();
  });

  it("ajoute, renomme et supprime un type propre", async () => {
    let own: DeviceType[] = [];
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const method = init?.method ?? "GET";
      calls.push(`${method} ${String(input)}`);
      if (method === "POST") {
        own = [PUMP];
        return Response.json(PUMP);
      }
      if (method === "PATCH") {
        own = [{ ...PUMP, name: "PAC" }];
        return Response.json(own[0]);
      }
      if (method === "DELETE") return new Response(null, { status: 409 });
      return Response.json(types(own));
    });
    renderScreen();

    const form = await screen.findByRole("form", { name: "Ajouter le type" });
    await userEvent.type(within(form).getByLabelText("Nom"), "Pompe à chaleur");
    await userEvent.selectOptions(within(form).getByLabelText("Sous le type"), "OtherLoad");
    await userEvent.click(within(form).getByRole("button", { name: "Ajouter le type" }));
    expect(await screen.findByText(/Type ajouté/)).toBeInTheDocument();

    const item = await screen.findByRole("listitem", { name: "Pompe à chaleur" });
    expect(item).toHaveTextContent("sous « Autre consommation »");
    const field = within(item).getByLabelText("Nom");
    await userEvent.clear(field);
    await userEvent.type(field, "PAC");
    await userEvent.click(within(item).getByRole("button", { name: "Renommer" }));
    expect(await screen.findByText("Type renommé.")).toBeInTheDocument();

    await userEvent.click(within(await screen.findByRole("listitem", { name: "PAC" })).getByRole("button", { name: "Supprimer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ce type est utilisé par un équipement");
    expect(calls).toContain("POST api/home/types");
    expect(calls).toContain("PATCH api/home/types/pompe-a-chaleur");
    expect(calls).toContain("DELETE api/home/types/pompe-a-chaleur");
  });
});
