// Fiche d'un appareil de Ma maison : réglages, capteurs, nom et type au même endroit (refonte de
// Ma maison, 2/2), appareils proposés par HA, retrait, recherche.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import type { Configuration } from "./configuration";
import HomeScreen from "./HomeScreen";
import type { DeviceProposal, EntityChoice, HomeModel, Role } from "./types";

const ENERGY_ROLES: Role[] = [
  "EnergyProduced",
  "EnergyImported",
  "EnergyExported",
  "EnergyCharged",
  "EnergyDischarged",
  "EnergyConsumed",
];
const POWER_ROLES: Role[] = ["PowerProduced", "PowerConsumed"];

const sensor = (entity_id: string, role: "EnergyConsumed" | "PowerConsumed" | "EnergyImported") => ({
  entity_id,
  role,
  name: null,
  unit: "kWh",
  resets_daily: false,
  excluded: false,
  issues: [],
});

// Capteurs de HA proposés au choix pour remplacer celui d'un appareil suivi.
const ENTITY = (entity_id: string, roles: Role[], name: string | null = null, resets_daily = false): EntityChoice => ({
  entity_id,
  name,
  unit: roles === POWER_ROLES ? "W" : "kWh",
  roles,
  resets_daily,
});

const ENTITIES: EntityChoice[] = [
  ENTITY("sensor.washer_energy", ENERGY_ROLES, "Lave-linge"),
  ENTITY("sensor.new_plug_energy", ENERGY_ROLES, "Prise du garage"),
  ENTITY("sensor.new_plug_daily_energy", ENERGY_ROLES, "Prise du garage, du jour", true),
  ENTITY("sensor.washer_power", POWER_ROLES),
  ENTITY("sensor.new_plug_power", POWER_ROLES, "Prise du garage"),
];

const PROPOSALS: DeviceProposal[] = [
  {
    key: "washer",
    kind: "WashingMachine",
    name: "Lave-linge",
    capacity_kwh: null,
    issues: [],
    sensors: [sensor("sensor.washer_energy", "EnergyConsumed"), sensor("sensor.washer_power", "PowerConsumed")],
  },
  {
    key: "grid",
    kind: "GridConnection",
    name: "Réseau",
    capacity_kwh: null,
    issues: [],
    sensors: [
      sensor("sensor.linky_hc", "EnergyImported"),
      { ...sensor("sensor.subscription_cost", "EnergyImported"), issues: [{ code: "not_energy_unit", params: { entity: "sensor.subscription_cost", unit: "EUR" } }] },
    ],
  },
  { key: "dryer", kind: "Dryer", name: "Sèche-linge", capacity_kwh: null, issues: [], sensors: [sensor("sensor.dryer_energy", "EnergyConsumed")] },
];

// Maison enregistrée : le lave-linge et le réseau ; le sèche-linge est seulement proposé.
const HOME: HomeModel = {
  devices: [
    {
      key: "washer",
      kind: "WashingMachine",
      name: "Lave-linge",
      capacity_kwh: null,
      sensors: [
        { entity_id: "sensor.washer_energy", role: "EnergyConsumed", resets_daily: false },
        { entity_id: "sensor.washer_power", role: "PowerConsumed", resets_daily: false },
      ],
    },
    {
      key: "grid",
      kind: "GridConnection",
      name: "Réseau",
      capacity_kwh: null,
      sensors: [
        { entity_id: "sensor.linky_hc", role: "EnergyImported", resets_daily: false },
        { entity_id: "sensor.subscription_cost", role: "EnergyImported", resets_daily: false },
      ],
    },
  ],
};

const CONFIGURATION: Configuration = {
  version: 1,
  devices: [
    { key: "washer", behavior: "CycleBehavior", automation: "RecommendAutomation", planned: true, default: true },
    { key: "grid", behavior: "GridBehavior", automation: "InformAutomation", planned: true, default: true },
  ],
  tariff: null,
};

type Sent = { url: string; body: unknown };

function mockApi(home: HomeModel = HOME, entities: EntityChoice[] | null = ENTITIES) {
  const sent: Sent[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as unknown;
      sent.push({ url, body });
      return Response.json(body);
    }
    if (url === "api/home") return Response.json(home);
    if (url === "api/configuration") return Response.json(CONFIGURATION);
    if (url === "api/home/entities") {
      return entities ? Response.json(entities) : new Response(null, { status: 503 });
    }
    if (url.startsWith("api/home/proposals")) return Response.json({ energy_dashboard: true, devices: PROPOSALS });
    if (url === "api/home/types") return Response.json({ parents: [], types: [], library: [] });
    return new Response(null, { status: 404 });
  });
  return sent;
}

function renderHome() {
  return render(
    <I18nProvider>
      <HomeScreen page="main" onNavigate={vi.fn()} />
    </I18nProvider>,
  );
}

async function openDevices() {
  await userEvent.click(await screen.findByRole("tab", { name: "Appareils" }));
}

describe("fiche d'un appareil", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renomme un appareil et retire un capteur, dans la même fiche que ses réglages", async () => {
    const sent = mockApi();
    renderHome();
    await openDevices();
    await userEvent.click(await screen.findByRole("button", { name: /^Lave-linge/ }));
    const sheet = screen.getByRole("dialog", { name: "Lave-linge" });
    expect(within(sheet).getByLabelText("Comportement")).toHaveValue("CycleBehavior");
    const details = within(sheet).getByText("Capteurs, nom et type").closest("details")!;
    expect(details.open).toBe(false); // rien à vérifier : replié

    await userEvent.click(within(sheet).getByText("Capteurs, nom et type"));
    const name = within(details).getByLabelText("Nom");
    await userEvent.clear(name);
    await userEvent.type(name, "Lave-linge du garage");
    await userEvent.click(within(details).getByLabelText("Retenir sensor.washer_power"));
    await userEvent.click(within(sheet).getByRole("button", { name: "Enregistrer les réglages" }));

    expect(await screen.findByText("Réglages enregistrés.")).toBeInTheDocument();
    expect(sent.map((s) => s.url)).toEqual(["api/home"]); // réglages inchangés : la maison seule
    const washer = (sent[0].body as HomeModel).devices.find((d) => d.key === "washer")!;
    expect(washer.name).toBe("Lave-linge du garage");
    expect(washer.sensors.map((s) => s.entity_id)).toEqual(["sensor.washer_energy"]);
  });

  it("remplace le capteur d'un appareil par un autre capteur de Home Assistant du même rôle", async () => {
    const sent = mockApi();
    renderHome();
    await openDevices();
    await userEvent.click(await screen.findByRole("button", { name: /^Lave-linge/ }));
    const sheet = screen.getByRole("dialog", { name: "Lave-linge" });
    const details = within(sheet).getByText("Capteurs, nom et type").closest("details")!;
    await userEvent.click(within(sheet).getByText("Capteurs, nom et type"));
    const energy = within(details).getByLabelText("Choisir le capteur Énergie consommée") as HTMLSelectElement;
    expect(energy).toHaveValue("sensor.washer_energy");
    // seuls les capteurs d'énergie sont proposés ; le capteur actuel reste en tête s'il a disparu de HA
    expect(Array.from(energy.options).map((option) => option.value)).toEqual([
      "sensor.washer_energy",
      "sensor.new_plug_energy",
      "sensor.new_plug_daily_energy",
    ]);
    const power = within(details).getByLabelText("Choisir le capteur Puissance consommée") as HTMLSelectElement;
    expect(Array.from(power.options).map((option) => option.value)).toEqual([
      "sensor.washer_power",
      "sensor.new_plug_power",
    ]);
    await userEvent.selectOptions(energy, "sensor.new_plug_daily_energy");
    await userEvent.click(within(sheet).getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByText("Réglages enregistrés.");
    expect(sent.map((s) => s.url)).toEqual(["api/home"]);
    const washer = (sent[0].body as HomeModel).devices.find((d) => d.key === "washer")!;
    expect(washer.sensors).toContainEqual({
      entity_id: "sensor.new_plug_daily_energy",
      role: "EnergyConsumed",
      resets_daily: true, // lu dans HA, le capteur choisi se remet à zéro chaque jour
    });
  });

  it("laisse le capteur actuel écrit, sans possibilité de le changer, quand HA n'est pas connecté", async () => {
    mockApi(HOME, null);
    renderHome();
    await openDevices();
    await userEvent.click(await screen.findByRole("button", { name: /^Lave-linge/ }));
    const sheet = screen.getByRole("dialog", { name: "Lave-linge" });
    const details = within(sheet).getByText("Capteurs, nom et type").closest("details")!;
    await userEvent.click(within(sheet).getByText("Capteurs, nom et type"));
    expect(within(details).getByText("sensor.washer_energy")).toBeInTheDocument();
    expect(within(details).queryByLabelText("Choisir le capteur Énergie consommée")).toBeNull();
  });

  it("montre les capteurs à vérifier du réseau et laisse en retirer un", async () => {
    const sent = mockApi();
    renderHome();
    await openDevices();
    await userEvent.click(screen.getByText("Réseau", { selector: "summary .ui-row-label" }));
    await userEvent.click(screen.getByRole("button", { name: "Réseau" }));
    const sheet = screen.getByRole("dialog", { name: "Réseau" });
    expect(within(sheet).getByText("Capteurs, nom et type").closest("details")!.open).toBe(true);
    await userEvent.click(within(sheet).getByLabelText("Retenir sensor.subscription_cost"));
    await userEvent.click(within(sheet).getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByText("Réglages enregistrés.");
    const grid = (sent[0].body as HomeModel).devices.find((d) => d.key === "grid")!;
    expect(grid.sensors.map((s) => s.entity_id)).toEqual(["sensor.linky_hc"]);
  });

  it("change le type : la maison d'abord, puis les réglages du nouveau type", async () => {
    const sent = mockApi();
    renderHome();
    await openDevices();
    await userEvent.click(await screen.findByRole("button", { name: /^Lave-linge/ }));
    const sheet = screen.getByRole("dialog", { name: "Lave-linge" });
    await userEvent.click(within(sheet).getByText("Capteurs, nom et type"));
    await userEvent.selectOptions(within(sheet).getByLabelText("Type"), "PoolPump");
    expect(within(sheet).getByLabelText("Comportement")).toHaveValue("RuntimeBehavior");
    await userEvent.click(within(sheet).getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByText("Réglages enregistrés.");
    expect(sent.map((s) => s.url)).toEqual(["api/home", "api/configuration"]);
    expect((sent[1].body as Configuration).devices.find((d) => d.key === "washer")).toMatchObject({
      behavior: "RuntimeBehavior",
      default: false,
    });
  });

  it("retire un appareil de la maison après confirmation", async () => {
    const sent = mockApi();
    renderHome();
    await openDevices();
    await userEvent.click(await screen.findByRole("button", { name: /^Lave-linge/ }));
    const sheet = screen.getByRole("dialog", { name: "Lave-linge" });
    await userEvent.click(within(sheet).getByText("Capteurs, nom et type"));
    await userEvent.click(within(sheet).getByRole("button", { name: "Retirer de ma maison" }));
    expect(sent).toHaveLength(0);
    await userEvent.click(within(sheet).getByRole("button", { name: "Confirmer le retrait" }));

    await screen.findByText("Réglages enregistrés.");
    expect((sent[0].body as HomeModel).devices.map((d) => d.key)).toEqual(["grid"]);
  });

  it("ajoute à la maison un appareil proposé par Home Assistant", async () => {
    const sent = mockApi();
    renderHome();
    await openDevices();
    const summary = await screen.findByText("Sèche-linge", { selector: "summary .ui-row-label" });
    await userEvent.click(summary);
    await userEvent.click(screen.getByRole("button", { name: "Sèche-linge" }));
    const sheet = screen.getByRole("dialog", { name: "Sèche-linge" });
    expect(within(sheet).getByText(/pas encore suivi/)).toBeInTheDocument();
    expect(within(sheet).queryByLabelText("Comportement")).toBeNull();
    await userEvent.click(within(sheet).getByRole("button", { name: "Ajouter à ma maison" }));

    await screen.findByText("Réglages enregistrés.");
    expect((sent[0].body as HomeModel).devices.map((d) => d.key)).toEqual(["washer", "grid", "dryer"]);
  });

  it("cherche un appareil parmi de nombreux appareils suivis", async () => {
    const plugs = Array.from({ length: 10 }, (_, n) => ({
      key: `plug-${n}`,
      kind: "OtherLoad" as const,
      name: n === 7 ? "Prise du congélateur" : `Prise ${n}`,
      capacity_kwh: null,
      sensors: [],
    }));
    mockApi({ devices: plugs });
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home") return Response.json({ devices: plugs });
      if (url === "api/configuration") {
        return Response.json({
          version: 1,
          devices: plugs.map((p) => ({ key: p.key, behavior: "UncontrolledBehavior", automation: "InformAutomation", planned: true, default: true })),
          tariff: null,
        });
      }
      return new Response(null, { status: 503 });
    });
    renderHome();
    await openDevices();
    await userEvent.click(await screen.findByText(/Prise 0, Prise 1, Prise 2 et 7 autres/));
    await userEvent.type(screen.getByRole("searchbox", { name: "Rechercher un appareil" }), "congelateur");
    expect(screen.getByRole("button", { name: "Prise du congélateur" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prise 3" })).toBeNull();
  });
});
