import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import HomeEditor from "./HomeEditor";
import type { HomeModel, HomeProposal } from "./types";

const PROPOSAL: HomeProposal = {
  energy_dashboard: true,
  devices: [
    {
      key: "Dryer-plug",
      kind: "Dryer",
      name: "Sèche Linge",
      capacity_kwh: null,
      issues: [{ code: "no_power_sensor", params: { entity: "sensor.plug_dryer_energy" } }],
      sensors: [
        {
          entity_id: "sensor.plug_dryer_energy",
          role: "EnergyConsumed",
          name: null,
          unit: "kWh",
          resets_daily: false,
          excluded: false,
          issues: [],
        },
      ],
    },
  ],
};

function mockApi(proposal: HomeProposal | number, saved: HomeModel = { devices: [] }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.startsWith("api/home/proposals")) {
      return typeof proposal === "number"
        ? new Response(null, { status: proposal })
        : Response.json(proposal);
    }
    if (url === "api/home" && init?.method === "PUT") {
      return Response.json(JSON.parse(String(init.body)));
    }
    if (url === "api/home") return Response.json(saved);
    if (url === "api/configuration") return Response.json({ version: 1, devices: [] });
    if (url === "api/templates") return Response.json([]);
    return new Response(null, { status: 404 });
  });
}

function renderScreen() {
  return render(
    <I18nProvider>
      <HomeEditor onSaved={vi.fn()} />
    </I18nProvider>,
  );
}

describe("HomeScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("affiche les équipements proposés et leurs anomalies traduites", async () => {
    mockApi(PROPOSAL);

    renderScreen();

    expect(await screen.findByDisplayValue("Sèche Linge")).toBeInTheDocument();
    expect(screen.getByText(/Aucune puissance trouvée pour sensor.plug_dryer_energy/)).toBeInTheDocument();
    expect(screen.getByText("1 point(s) à vérifier.")).toBeInTheDocument();
  });

  it("propose les types propres et enregistre celui choisi avec son parent", async () => {
    const own = { key: "seche-linge-a-pompe", name: "Sèche-linge à pompe", parent: "Dryer" };
    const sent: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("api/home/proposals")) return Response.json(PROPOSAL);
      if (url === "api/home/types") return Response.json({ parents: ["Dryer"], types: [own], library: [] });
      if (url === "api/home" && init?.method === "PUT") {
        sent.push(JSON.parse(String(init.body)));
        return Response.json(sent[0]);
      }
      if (url === "api/home") return Response.json({ devices: [] });
      if (url === "api/configuration") return Response.json({ version: 1, devices: [] });
      return new Response(null, { status: 404 });
    });
    renderScreen();

    const kind = await screen.findByDisplayValue("Sèche-linge");
    await userEvent.selectOptions(kind, "custom:seche-linge-a-pompe");
    expect(kind).toHaveDisplayValue("Sèche-linge à pompe (Sèche-linge)");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Maison enregistrée.")).toBeInTheDocument();
    expect(sent[0]).toMatchObject({ devices: [{ kind: "Dryer", custom_type: "seche-linge-a-pompe" }] });
  });

  it("ajoute un équipement absent du tableau Énergie, avec ses capteurs", async () => {
    const sent: { devices: { key: string; kind: string; sensors: { entity_id: string; role: string }[] }[] }[] = [];
    const library = [{ kind: "OtherLoad", behaviors: ["UncontrolledBehavior"], roles: ["PowerConsumed", "EnergyConsumed"], subtypes: true }];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("api/home/proposals")) return Response.json(PROPOSAL);
      if (url === "api/home/types") return Response.json({ parents: [], types: [], library });
      if (url === "api/home/entities") {
        return Response.json([
          { entity_id: "sensor.pump_power", name: "Pompe", unit: "W", roles: ["PowerConsumed", "PowerProduced"] },
          { entity_id: "sensor.pump_energy", name: "Pompe", unit: "kWh", roles: ["EnergyConsumed"] },
        ]);
      }
      if (url === "api/home" && init?.method === "PUT") {
        sent.push(JSON.parse(String(init.body)));
        return Response.json(sent[0]);
      }
      if (url === "api/home") return Response.json({ devices: [] });
      if (url === "api/configuration") return Response.json({ version: 1, devices: [] });
      return new Response(null, { status: 404 });
    });
    renderScreen();

    await userEvent.click(await screen.findByRole("button", { name: "Ajouter un équipement" }));
    const form = screen.getByRole("group", { name: "Ajouter un équipement absent du tableau Énergie" });
    await userEvent.type(within(form).getByLabelText("Nom"), "Pompe de relevage");
    await userEvent.selectOptions(await within(form).findByLabelText("Puissance consommée"), "sensor.pump_power");
    await userEvent.selectOptions(within(form).getByLabelText("Énergie consommée"), "sensor.pump_energy");
    await userEvent.click(within(form).getByRole("button", { name: "Ajouter" }));
    expect(screen.getByDisplayValue("Pompe de relevage")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Maison enregistrée.")).toBeInTheDocument();
    const pump = sent[0].devices.find((d) => d.key === "manual-pompe-de-relevage");
    expect(pump).toMatchObject({ kind: "OtherLoad" });
    expect(pump?.sensors).toEqual([
      { entity_id: "sensor.pump_power", role: "PowerConsumed", resets_daily: false },
      { entity_id: "sensor.pump_energy", role: "EnergyConsumed", resets_daily: false },
    ]);
  });

  it("enregistre le modèle corrigé", async () => {
    const fetchMock = mockApi(PROPOSAL);
    renderScreen();
    const name = await screen.findByDisplayValue("Sèche Linge");

    await userEvent.clear(name);
    await userEvent.type(name, "Sèche-linge du cellier");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Maison enregistrée.")).toBeInTheDocument();
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      devices: [
        {
          key: "Dryer-plug",
          kind: "Dryer",
          custom_type: null,
          name: "Sèche-linge du cellier",
          capacity_kwh: null,
          sensors: [
            { entity_id: "sensor.plug_dryer_energy", role: "EnergyConsumed", resets_daily: false },
          ],
        },
      ],
    });
  });

  it("décoche un capteur seul et ne l'enregistre pas", async () => {
    const fetchMock = mockApi(PROPOSAL);
    renderScreen();

    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Retenir sensor.plug_dryer_energy" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Maison enregistrée.")).toBeInTheDocument();
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body)).devices[0].sensors).toEqual([]);
  });

  it("signale un Home Assistant non connecté", async () => {
    mockApi(503);

    renderScreen();

    expect(await screen.findByRole("alert")).toHaveTextContent("Home Assistant n'est pas connecté");
  });

  it("signale un tableau Énergie absent", async () => {
    mockApi({ energy_dashboard: false, devices: [] });

    renderScreen();

    expect(await screen.findByRole("alert")).toHaveTextContent("tableau Énergie");
  });
});
