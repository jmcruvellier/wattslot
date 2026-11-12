// Premiers pas guidés (lot 6b.6).

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HomeProposal } from "../home/types";
import { I18nProvider } from "../i18n/I18nProvider";
import Onboarding from "./Onboarding";
import type { Setup, SetupStep } from "./StartScreen";

function step(key: string, state: SetupStep["state"]): SetupStep {
  return { key, state, required: true, reason: null, params: {}, target: null };
}

const sensor = (entity_id: string, role: string) => ({
  entity_id,
  role,
  name: null,
  unit: null,
  resets_daily: false,
  excluded: false,
  issues: [],
});

const PROPOSAL = {
  energy_dashboard: true,
  devices: [
    { key: "solar", kind: "SolarInstallation", name: "Panneaux solaires", sensors: [sensor("sensor.pv", "EnergyProduced")], capacity_kwh: null, issues: [] },
    { key: "battery", kind: "Battery", name: "Batterie", sensors: [sensor("sensor.soc", "StateOfCharge")], capacity_kwh: 5.12, issues: [] },
    { key: "fridge", kind: "OtherLoad", name: "Frigo", sensors: [sensor("sensor.fridge", "EnergyConsumed")], capacity_kwh: null, issues: [] },
  ],
} as unknown as HomeProposal;

const TEMPLATES = [
  { key: "hp_hc", name: { fr: "Heures creuses" }, description: { fr: "Tarif à deux prix" }, tariff_kind: "TimeOfUseTariff", devices: [] },
  { key: "tempo", name: { fr: "Tempo" }, description: { fr: "Couleur du jour" }, tariff_kind: "DayColorTariff", devices: [] },
];

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/home/proposals") return Response.json(PROPOSAL);
    if (url === "api/home" && init?.method === "PUT") return Response.json(JSON.parse(String(init.body)));
    if (url === "api/home") return Response.json({ devices: [] });
    if (url === "api/templates") return Response.json(TEMPLATES);
    if (url.endsWith("/apply")) return Response.json({});
    return new Response(null, { status: 404 });
  });
}

function renderFlow(setup: Setup, handlers: Partial<Record<"onNavigate" | "onRun" | "onChanged", () => void>> = {}) {
  const props = { onNavigate: vi.fn(), onRun: vi.fn(), onChanged: vi.fn(), ...handlers };
  render(
    <I18nProvider>
      <Onboarding setup={setup} running={false} {...props} />
    </I18nProvider>,
  );
  return props;
}

const CONNECTED: Setup = {
  ready: false,
  steps: [step("connection", "done"), step("home", "todo"), step("tariff", "todo"), step("first_plan", "todo")],
};

describe("Onboarding", () => {
  beforeEach(() => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("guide de la maison au premier plan, une question par écran", async () => {
    const user = userEvent.setup();
    const fetch = mockApi();
    const { onChanged, onRun } = renderFlow(CONNECTED);

    // Connexion faite : trois étapes, la maison d'abord.
    expect(screen.getByText("Étape 1 sur 3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Voici ce que nous avons trouvé chez vous" })).toBeInTheDocument();
    expect(await screen.findByText("5,1 kWh, chargée au meilleur moment")).toBeInTheDocument();
    expect(screen.getByText("Suivi seulement")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Frigo/ }));
    await user.click(screen.getByRole("button", { name: "C'est bon, continuer" }));

    const put = fetch.mock.calls.find(([url, init]) => url === "api/home" && init?.method === "PUT");
    const saved = JSON.parse(String(put?.[1]?.body)) as { devices: { key: string }[]; supply: string };
    expect(saved.devices.map((device) => device.key)).toEqual(["solar", "battery"]);
    // Rien ne dit une phase, et l'utilisateur n'a rien changé : monophasé.
    expect(saved.supply).toBe("SinglePhaseSupply");
    expect(onChanged).toHaveBeenCalled();

    // Contrat : un modèle sans entités s'applique ici ; Tempo attend son capteur.
    expect(await screen.findByText("Étape 2 sur 3")).toBeInTheDocument();
    await user.click(await screen.findByRole("radio", { name: /Tempo/ }));
    expect(screen.getByRole("button", { name: "Utiliser ce modèle" })).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: /Heures creuses/ }));
    await user.click(screen.getByRole("button", { name: "Utiliser ce modèle" }));
    expect(fetch.mock.calls.some(([url]) => url === "api/templates/hp_hc/apply")).toBe(true);

    // Premier plan.
    expect(await screen.findByText("Étape 3 sur 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Calculer mon premier plan" }));
    expect(onRun).toHaveBeenCalled();
  });

  it("demande l'alimentation : le triphasé que la détection propose, ou celui que l'on choisit", async () => {
    const user = userEvent.setup();
    const fetch = mockApi();
    renderFlow(CONNECTED);

    // Rien ne dit une phase : monophasé proposé, sans remarque ; on choisit le triphasé.
    const supply = await screen.findByRole("combobox", { name: "Alimentation" });
    expect(supply).toHaveValue("SinglePhaseSupply");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    await user.selectOptions(supply, "ThreePhaseSupply");
    expect(screen.getByText(/il restera à indiquer la phase de chaque appareil/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "C'est bon, continuer" }));

    const put = fetch.mock.calls.find(([url, init]) => url === "api/home" && init?.method === "PUT");
    expect((JSON.parse(String(put?.[1]?.body)) as { supply: string }).supply).toBe("ThreePhaseSupply");
  });

  it("part du triphasé, et le dit, quand des noms de Home Assistant disent une phase", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home/proposals") return Response.json({ ...PROPOSAL, supply: "ThreePhaseSupply" });
      if (url === "api/home") return Response.json({ devices: [], supply: "SinglePhaseSupply" });
      return new Response(null, { status: 404 });
    });
    renderFlow(CONNECTED);

    expect(await screen.findByRole("combobox", { name: "Alimentation" })).toHaveValue("ThreePhaseSupply");
    expect(screen.getByRole("note")).toHaveTextContent("sans doute en triphasé");
  });

  it("propose la connexion quand elle manque, et permet de la passer", async () => {
    const user = userEvent.setup();
    mockApi();
    const setup: Setup = { ...CONNECTED, steps: [step("connection", "todo"), ...CONNECTED.steps.slice(1)] };
    const { onNavigate } = renderFlow(setup);

    expect(screen.getByText("Étape 1 sur 4")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Se connecter à Home Assistant" }));
    expect(onNavigate).toHaveBeenCalledWith("connection");
    await user.click(screen.getByRole("button", { name: "Passer" }));
    expect(screen.getByText("Étape 2 sur 4")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retour" }));
    expect(screen.getByText("Étape 1 sur 4")).toBeInTheDocument();
  });

  it("sans appareil à placer dans le tableau Énergie : le dit et propose d'en ajouter un", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home/proposals") {
        return Response.json({ ...PROPOSAL, devices: PROPOSAL.devices.filter((d) => d.kind !== "OtherLoad") });
      }
      if (url === "api/home") return Response.json({ devices: [] });
      return new Response(null, { status: 404 });
    });
    const { onNavigate } = renderFlow(CONNECTED);

    expect(await screen.findByText(/Aucun appareil à placer n'a été trouvé/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ajouter un appareil" }));
    expect(onNavigate).toHaveBeenCalledWith("devices#add-device");
  });

  it("Tempo : le capteur du jour se choisit sur place, parmi ceux de Home Assistant", async () => {
    const user = userEvent.setup();
    const fetch = mockApi();
    const candidates = [
      { entity_id: "sensor.tempo_today", name: "Couleur du jour", state: "Bleu", tomorrow: false },
      { entity_id: "sensor.tempo_tomorrow", name: "Couleur de demain", state: "Blanc", tomorrow: true },
    ];
    fetch.mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/templates") return Response.json(TEMPLATES);
      if (url === "api/templates/tempo/entities") return Response.json(candidates);
      if (url.endsWith("/apply")) return Response.json({});
      return new Response(null, { status: 404 });
    });
    const setup: Setup = { ...CONNECTED, steps: [step("connection", "done"), step("home", "done"), step("tariff", "todo"), step("first_plan", "todo")] };
    renderFlow(setup);

    await user.click(await screen.findByRole("radio", { name: /Tempo/ }));
    // Proposés d'office : le premier capteur du jour, le premier du lendemain.
    const today = await screen.findByRole("combobox", { name: "Capteur du jour annoncé" });
    expect(today).toHaveValue("sensor.tempo_today");
    expect(screen.getByRole("combobox", { name: "Capteur du lendemain" })).toHaveValue("sensor.tempo_tomorrow");

    // Une autre entité, saisie à la main.
    await user.selectOptions(today, "Autre entité…");
    expect(screen.getByRole("button", { name: "Utiliser ce modèle" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Identifiant de l'entité" }), "sensor.ma_couleur");
    await user.click(screen.getByRole("button", { name: "Utiliser ce modèle" }));

    const apply = fetch.mock.calls.find(([url]) => url === "api/templates/tempo/apply");
    expect(JSON.parse(String(apply?.[1]?.body))).toEqual({
      color_entity: "sensor.ma_couleur",
      color_tomorrow_entity: "sensor.tempo_tomorrow",
    });
    expect(await screen.findByRole("heading", { name: "Tout est prêt" })).toBeInTheDocument();
  });

  it("Tempo sans entité candidate : l'identifiant du capteur se saisit", async () => {
    const user = userEvent.setup();
    const fetch = mockApi();
    const setup: Setup = { ...CONNECTED, steps: [step("connection", "done"), step("home", "done"), step("tariff", "todo"), step("first_plan", "todo")] };
    renderFlow(setup);

    await user.click(await screen.findByRole("radio", { name: /Tempo/ }));
    expect(await screen.findByText(/Aucune entité de Home Assistant ne ressemble/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Utiliser ce modèle" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Capteur du jour annoncé" }), "sensor.tempo");
    await user.click(screen.getByRole("button", { name: "Utiliser ce modèle" }));

    const apply = fetch.mock.calls.find(([url]) => url === "api/templates/tempo/apply");
    expect(JSON.parse(String(apply?.[1]?.body))).toEqual({ color_entity: "sensor.tempo" });
  });

  it("reprend à la première étape pas encore faite, et laisse le contrat pour plus tard", async () => {
    const user = userEvent.setup();
    mockApi();
    const setup: Setup = { ...CONNECTED, steps: [step("connection", "done"), step("home", "done"), step("tariff", "todo"), step("first_plan", "todo")] };
    renderFlow(setup);

    expect(screen.getByText("Étape 2 sur 3")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Je réglerai plus tard" }));
    expect(screen.getByRole("heading", { name: "Tout est prêt" })).toBeInTheDocument();
  });

  it("ne parle pas de batterie quand la maison n'en a pas", () => {
    mockApi();
    const setup: Setup = {
      ...CONNECTED,
      steps: [step("connection", "done"), step("home", "done"), step("tariff", "done"), step("battery", "not_applicable"), step("first_plan", "todo")],
    };
    renderFlow(setup);

    expect(screen.getByText(/calcule votre premier plan/)).not.toHaveTextContent("batterie");
  });

  it("dit ce qui manque avant le premier plan au lieu de proposer un calcul refusé", async () => {
    const user = userEvent.setup();
    mockApi();
    const forecast: SetupStep = { ...step("forecast", "todo"), reason: "no_forecast", target: "home#solar" };
    const setup: Setup = {
      ...CONNECTED,
      steps: [step("connection", "done"), step("home", "done"), step("tariff", "done"), forecast, step("first_plan", "blocked")],
    };
    const { onNavigate } = renderFlow(setup);

    expect(screen.getByRole("heading", { name: "Encore une étape" })).toBeInTheDocument();
    expect(screen.getByText("Prévision solaire")).toBeInTheDocument();
    expect(screen.getByText(/Aucune prévision solaire/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Calculer mon premier plan" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Y aller" }));
    expect(onNavigate).toHaveBeenCalledWith("home#solar");
  });
});
