// Phases détectées dans les noms de Home Assistant : proposées à la première validation de la
// maison, et signalées dans « Mon raccordement » à une maison déjà enregistrée en monophasé.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import type { Configuration } from "./configuration";
import { buildDraft, firstModel, toModel } from "./draft";
import HomeScreen from "./HomeScreen";
import type { DeviceProposal, HomeModel, HomeProposal, SensorProposal } from "./types";

const sensor = (entity_id: string, role: SensorProposal["role"], phase: SensorProposal["phase"] = null): SensorProposal => ({
  entity_id,
  role,
  name: null,
  unit: "kWh",
  resets_daily: false,
  excluded: false,
  issues: [],
  phase,
});

const PROPOSALS: DeviceProposal[] = [
  {
    key: "grid",
    kind: "GridConnection",
    name: "Réseau",
    capacity_kwh: null,
    issues: [],
    sensors: [
      sensor("sensor.meter_total", "EnergyImported"),
      sensor("sensor.meter_phase_a", "EnergyImported", "PhaseL1"),
      sensor("sensor.meter_phase_b", "EnergyImported", "PhaseL2"),
    ],
  },
  {
    key: "battery-l2",
    kind: "Battery",
    name: "Batterie L2",
    capacity_kwh: 5,
    issues: [],
    phase: "PhaseL2",
    sensors: [sensor("sensor.battery_l2_soc", "StateOfCharge")],
  },
];
const EMPTY: HomeModel = { devices: [] };

describe("brouillon d'une maison dont les noms disent des phases", () => {
  it("propose à la première validation la phase des appareils et des capteurs du réseau", () => {
    const model = firstModel(buildDraft(PROPOSALS, EMPTY), "ThreePhaseSupply");

    expect(model.supply).toBe("ThreePhaseSupply");
    expect(model.devices.find((d) => d.key === "battery-l2")?.phase).toBe("PhaseL2");
    expect(model.devices.find((d) => d.key === "grid")?.sensors).toEqual([
      { entity_id: "sensor.meter_total", role: "EnergyImported", resets_daily: false },
      { entity_id: "sensor.meter_phase_a", role: "EnergyImported", resets_daily: false, phase: "PhaseL1" },
      { entity_id: "sensor.meter_phase_b", role: "EnergyImported", resets_daily: false, phase: "PhaseL2" },
    ]);
    // Rien ne dit une phase : l'alimentation n'est pas envoyée, le serveur garde la sienne.
    expect(firstModel(buildDraft(PROPOSALS, EMPTY), null)).not.toHaveProperty("supply");
  });

  it("garde ce que l'utilisateur a enregistré, et propose le reste sans le retenir", () => {
    const saved: HomeModel = {
      devices: [
        {
          key: "grid",
          kind: "GridConnection",
          name: "Réseau",
          capacity_kwh: null,
          // Enregistré comme mesure du total, bien que son nom dise une phase.
          sensors: [{ entity_id: "sensor.meter_phase_a", role: "EnergyImported", resets_daily: false }],
        },
        { key: "battery-l2", kind: "Battery", name: "Batterie", capacity_kwh: 5, phase: "PhaseL3", sensors: [] },
      ],
    };

    const draft = buildDraft(PROPOSALS, saved);

    const grid = draft.find((d) => d.key === "grid")!;
    expect(grid.sensors.map((s) => [s.entity_id, s.included, s.phase])).toEqual([
      ["sensor.meter_total", false, null],
      ["sensor.meter_phase_a", true, null],
      ["sensor.meter_phase_b", false, "PhaseL2"],
    ]);
    expect(draft.find((d) => d.key === "battery-l2")?.phase).toBe("PhaseL3");
    expect(toModel(draft).devices.find((d) => d.key === "grid")?.sensors).toHaveLength(1);
  });
});

const CONFIGURATION: Configuration = { version: 1, devices: [], tariff: null };

function mockApi(home: HomeModel, proposal: HomeProposal) {
  const sent: { url: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as unknown;
      sent.push({ url, body });
      return Response.json(body);
    }
    if (url === "api/home") return Response.json(home);
    if (url === "api/configuration") return Response.json(CONFIGURATION);
    if (url.startsWith("api/home/proposals")) return Response.json(proposal);
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

describe("maison dont les noms disent des phases", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("enregistre la maison en triphasé à sa première validation", async () => {
    const sent = mockApi(EMPTY, { energy_dashboard: true, devices: PROPOSALS, supply: "ThreePhaseSupply" });
    renderHome();

    await userEvent.click(await screen.findByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Maison enregistrée.")).toBeInTheDocument();
    const model = sent[0].body as HomeModel;
    expect(model.supply).toBe("ThreePhaseSupply");
    expect(model.devices.find((d) => d.key === "battery-l2")?.phase).toBe("PhaseL2");
  });

  it("signale dans « Mon raccordement » une maison en monophasé qui semble en triphasé", async () => {
    const home: HomeModel = {
      devices: [{ key: "grid", kind: "GridConnection", name: "Réseau", capacity_kwh: null, sensors: [] }],
    };
    mockApi(home, { energy_dashboard: true, devices: PROPOSALS, supply: "ThreePhaseSupply" });
    renderHome();
    await userEvent.click(await screen.findByRole("tab", { name: "L'essentiel" }));
    await userEvent.click(await screen.findByRole("button", { name: /^Mon raccordement/ }));
    const sheet = await screen.findByRole("dialog", { name: "Raccordement au réseau" });

    expect(await within(sheet).findByRole("note")).toHaveTextContent("votre maison est sans doute en triphasé");

    // Une fois le triphasé choisi, la remarque n'a plus lieu d'être.
    await userEvent.selectOptions(within(sheet).getByLabelText("Alimentation"), "Triphasé");
    expect(within(sheet).queryByRole("note")).toBeNull();
  });

  it("ne signale rien quand aucun nom ne dit une phase", async () => {
    const home: HomeModel = {
      devices: [{ key: "grid", kind: "GridConnection", name: "Réseau", capacity_kwh: null, sensors: [] }],
    };
    mockApi(home, { energy_dashboard: true, devices: [], supply: null });
    renderHome();
    await userEvent.click(await screen.findByRole("tab", { name: "L'essentiel" }));
    await userEvent.click(await screen.findByRole("button", { name: /^Mon raccordement/ }));
    const sheet = await screen.findByRole("dialog", { name: "Raccordement au réseau" });

    await within(sheet).findByLabelText("Alimentation");
    expect(within(sheet).queryByRole("note")).toBeNull();
  });
});
