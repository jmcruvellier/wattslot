// Réglages du calcul de Ma maison (lot 3.1 et suivants), chacun dans sa feuille depuis la refonte :
// on ouvre l'onglet, la ligne du réglage, on modifie, on enregistre.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { DEFAULT_RUNTIME, type Configuration } from "./configuration";
import HomeScreen from "./HomeScreen";
import type { HomeModel } from "./types";

const HOME: HomeModel = {
  devices: [
    { key: "solar", kind: "SolarInstallation", name: "Panneaux", sensors: [], capacity_kwh: null },
    { key: "washer", kind: "WashingMachine", name: "Lave-linge", sensors: [], capacity_kwh: null },
    { key: "pool", kind: "PoolPump", name: "Piscine", sensors: [], capacity_kwh: null },
  ],
};

const CONFIGURATION: Configuration = {
  version: 1,
  devices: [
    { key: "solar", behavior: "ProductionBehavior", automation: "InformAutomation", planned: true, default: true },
    { key: "washer", behavior: "CycleBehavior", automation: "RecommendAutomation", planned: true, default: true },
    { key: "pool", behavior: "RuntimeBehavior", automation: "RecommendAutomation", planned: true, default: true },
  ],
  tariff: null,
};

// API simulée : la maison, la configuration, et ce que renvoie l'enregistrement.
function mockApi(
  put: (body: Configuration) => Response = (body) => Response.json(body),
  { home = HOME, configuration = CONFIGURATION, other }: {
    home?: HomeModel;
    configuration?: Configuration;
    other?: (url: string) => Response | undefined;
  } = {},
) {
  // Configuration enregistrée : relue après chaque enregistrement réussi.
  let current = configuration;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/home") return Response.json(home);
    if (url === "api/configuration" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as Configuration;
      const response = put(body);
      if (response.ok) current = body;
      return response;
    }
    if (url === "api/configuration") return Response.json(current);
    return other?.(url) ?? new Response(null, { status: 404 });
  });
}

// Enregistrements reçus par l'API simulée.
function recording(): [Configuration[], (body: Configuration) => Response] {
  const sent: Configuration[] = [];
  return [
    sent,
    (body) => {
      sent.push(body);
      return Response.json(body);
    },
  ];
}

function renderHome() {
  return render(
    <I18nProvider>
      <HomeScreen page="main" onNavigate={vi.fn()} />
    </I18nProvider>,
  );
}

// Ouvre la feuille d'une ligne, dans son onglet ; renvoie la feuille.
async function openSheet(tab: "L'essentiel" | "Appareils", row: RegExp, title: string) {
  await userEvent.click(await screen.findByRole("tab", { name: tab }));
  await userEvent.click(await screen.findByRole("button", { name: row }));
  return screen.getByRole("dialog", { name: title });
}

async function save(sheet: HTMLElement) {
  await userEvent.click(within(sheet).getByRole("button", { name: "Enregistrer les réglages" }));
}

async function saved() {
  expect(await screen.findByRole("status")).toHaveTextContent("Réglages enregistrés.");
  expect(screen.queryByRole("dialog")).toBeNull();
}

describe("réglages de Ma maison", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("propose les comportements du type et enregistre les choix d'un appareil", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    // Production : réglée par « Panneaux » dans L'essentiel ; parmi les appareils, repliée avec
    // le réseau et la batterie (ses capteurs).
    await userEvent.click(await screen.findByRole("tab", { name: "Appareils" }));
    expect(screen.getByText("Panneaux", { selector: "summary .ui-row-label" })).toBeInTheDocument();

    let pool = await openSheet("Appareils", /^Piscine/, "Piscine");
    const select = within(pool).getByLabelText("Comportement") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual([
      "Durée de fonctionnement à placer",
      "Consommation seulement suivie",
    ]);
    await userEvent.selectOptions(select, "UncontrolledBehavior");
    expect(within(pool).queryByRole("checkbox")).toBeNull(); // non pilotable : rien à placer
    await save(pool);
    await saved();
    let devices = Object.fromEntries(sent[0].devices.map((d) => [d.key, d]));
    expect(devices.pool).toMatchObject({ behavior: "UncontrolledBehavior", automation: "InformAutomation", default: false });
    expect(devices.washer.default).toBe(true); // pas touché : pas changé

    pool = await openSheet("Appareils", /^Lave-linge/, "Lave-linge");
    await userEvent.click(within(pool).getByLabelText(/Pris en compte par le calcul/));
    await save(pool);
    await saved();
    devices = Object.fromEntries(sent[1].devices.map((d) => [d.key, d]));
    expect(devices.washer).toMatchObject({ planned: false, default: false });
    expect(devices.pool.behavior).toBe("UncontrolledBehavior"); // l'enregistrement précédent est gardé
    expect(devices.solar.default).toBe(true);
  });

  it("affiche dans la feuille les anomalies renvoyées par l'API", async () => {
    mockApi(() =>
      Response.json({ detail: [{ code: "behavior_not_allowed", device: "pool", params: {} }] }, { status: 422 }),
    );
    renderHome();

    const pool = await openSheet("Appareils", /^Piscine/, "Piscine");
    await userEvent.selectOptions(within(pool).getByLabelText("Comportement"), "UncontrolledBehavior");
    await save(pool);

    expect(await within(pool).findByRole("alert")).toHaveTextContent(
      "Piscine : comportement impossible pour ce type d'équipement.",
    );
  });

  it("règle le tarif : heures creuses et pleines, revente, retour au prix par défaut", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    let sheet = await openSheet("L'essentiel", /^Mon contrat/, "Tarif de l'électricité");
    expect(within(sheet).getByText(/prix unique de 0.25\s€\/kWh/)).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("button", { name: "Définir des heures creuses et pleines" }));
    const base = within(sheet).getByLabelText(/Prix hors des plages/);
    await userEvent.clear(base);
    await userEvent.type(base, "0.179076");
    const nightBand = within(sheet).getByRole("listitem", { name: "Plage 1" });
    await userEvent.selectOptions(within(nightBand).getByLabelText("De"), "1");
    await userEvent.selectOptions(within(nightBand).getByLabelText("Minutes de début"), "30");
    await userEvent.selectOptions(within(nightBand).getByLabelText("à"), "5");
    await userEvent.selectOptions(within(nightBand).getByLabelText("Minutes de fin"), "38");
    const nightPrice = within(nightBand).getByLabelText(/^prix/);
    await userEvent.clear(nightPrice);
    await userEvent.type(nightPrice, "0.138252");
    await userEvent.click(within(sheet).getByRole("button", { name: "Ajouter une plage" }));
    await userEvent.click(within(sheet).getByRole("listitem", { name: "Plage 3" }).querySelector("button")!);
    const subscription = within(sheet).getByLabelText(/Abonnement/);
    await userEvent.clear(subscription);
    await userEvent.type(subscription, "15.5");
    await userEvent.type(within(sheet).getByLabelText(/Puissance souscrite/), "9");
    await save(sheet);

    await saved();
    expect(sent[0].tariff).toEqual({
      kind: "TimeOfUseTariff",
      base_eur_kwh: 0.179076,
      bands: [
        { start_hour: 1, start_minute: 30, end_hour: 5, end_minute: 38, eur_kwh: 0.138252, weekdays: [], months: [] },
        { start_hour: 22, start_minute: 0, end_hour: 24, end_minute: 0, eur_kwh: 0.15, weekdays: [], months: [] },
      ],
      export_eur_kwh: 0,
      colors: [],
      color_entity: null,
      color_tomorrow_entity: null,
      color_day_start_hour: 0,
      price_entity: null,
      export_entity: null,
      price_factor: 1,
      subscription_eur_month: 15.5,
      contract_kva: 9,
    });

    sheet = await openSheet("L'essentiel", /^Mon contrat/, "Tarif de l'électricité");
    await userEvent.click(within(sheet).getByRole("button", { name: "Revenir au prix par défaut" }));
    await save(sheet);
    await saved();
    expect(sent[1].tariff).toBeNull();
  }, 15_000); // beaucoup de saisie : plus de 5 s quand toute la suite tourne en parallèle

  it("règle un tarif Tempo et un prix dynamique", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    let sheet = await openSheet("L'essentiel", /^Mon contrat/, "Tarif de l'électricité");
    await userEvent.click(within(sheet).getByRole("button", { name: "Définir un tarif par couleur de jour (Tempo)" }));
    await userEvent.type(within(sheet).getByLabelText("Capteur de la couleur du jour"), "sensor.tempo_today");
    const redPrice = within(sheet).getByRole("group", { name: "Couleur Rouge" }).querySelector("input[type=number]")!;
    await userEvent.clear(redPrice);
    await userEvent.type(redPrice, "0.7562");
    await save(sheet);

    await saved();
    const tempo = sent[0].tariff!;
    expect(tempo.kind).toBe("DayColorTariff");
    expect(tempo.color_entity).toBe("sensor.tempo_today");
    expect(tempo.color_day_start_hour).toBe(6);
    expect(tempo.colors.map((c) => [c.color, c.base_eur_kwh])).toEqual([
      ["Bleu", 0.16],
      ["Blanc", 0.19],
      ["Rouge", 0.7562],
    ]);

    sheet = await openSheet("L'essentiel", /^Mon contrat/, "Tarif de l'électricité");
    await userEvent.selectOptions(within(sheet).getByLabelText("Type de tarif"), "DynamicTariff");
    await userEvent.type(within(sheet).getByLabelText("Capteur du prix"), "sensor.nordpool");
    await userEvent.selectOptions(within(sheet).getByLabelText("Unité des prix lus dans Home Assistant"), "0.001");
    await save(sheet);

    await saved();
    expect(sent[1].tariff).toMatchObject({ kind: "DynamicTariff", price_entity: "sensor.nordpool", price_factor: 0.001 });
  }, 15_000);

  it("propose un tarif d'après le tableau Énergie", async () => {
    const proposal = {
      kind: "DynamicTariff",
      base_eur_kwh: 0.25,
      bands: [],
      export_eur_kwh: 0.06,
      colors: [],
      color_entity: null,
      color_tomorrow_entity: null,
      color_day_start_hour: 0,
      price_entity: "sensor.spot",
      export_entity: null,
      price_factor: 1,
    };
    mockApi(undefined, {
      other: (url) => (url === "api/configuration/tariff-proposal" ? Response.json(proposal) : undefined),
    });
    renderHome();

    const sheet = await openSheet("L'essentiel", /^Mon contrat/, "Tarif de l'électricité");
    await userEvent.click(within(sheet).getByRole("button", { name: "Proposer d'après le tableau Énergie" }));

    expect(await within(sheet).findByLabelText("Capteur du prix")).toHaveValue("sensor.spot");
    expect(within(sheet).getByLabelText("Type de tarif")).toHaveValue("DynamicTariff");
  });

  it("signale un tableau Énergie sans prix ou un Home Assistant absent", async () => {
    let status = 200;
    mockApi(undefined, {
      other: () => (status === 200 ? Response.json(null) : new Response(null, { status })),
    });
    renderHome();

    const sheet = await openSheet("L'essentiel", /^Mon contrat/, "Tarif de l'électricité");
    const button = within(sheet).getByRole("button", { name: "Proposer d'après le tableau Énergie" });
    await userEvent.click(button);
    expect(await within(sheet).findByRole("status")).toHaveTextContent("ne déclare aucun prix");
    status = 503;
    await userEvent.click(button);
    expect(await within(sheet).findByText(/Home Assistant n'est pas connecté/)).toBeInTheDocument();
  });

  it("règle la batterie quand la maison en a une", async () => {
    const home: HomeModel = {
      devices: [...HOME.devices, { key: "battery", kind: "Battery", name: "Batterie", sensors: [], capacity_kwh: 5.12 }],
    };
    const [sent, put] = recording();
    mockApi(put, { home });
    renderHome();

    const sheet = await openSheet("L'essentiel", /^Batterie/, "Batterie");
    const charge = within(sheet).getByLabelText(/Puissance de charge maximale/);
    expect(charge).toHaveAttribute("placeholder", "2560"); // 0,5 C de 5,12 kWh
    expect(within(sheet).getByText(/Réglages par défaut : modifiez-les/)).toBeInTheDocument();
    await userEvent.type(charge, "2500");
    await userEvent.type(within(sheet).getByLabelText(/Puissance de décharge maximale/), "800");
    const floor = within(sheet).getByLabelText(/Ne jamais décharger en dessous de/);
    await userEvent.clear(floor);
    await userEvent.type(floor, "12");
    await userEvent.selectOptions(within(sheet).getAllByLabelText("de")[0], "6");
    await save(sheet);

    await saved();
    expect(sent[0].battery).toEqual({
      charge_max_w: 2500,
      discharge_max_w: 800,
      floor_percent: 12,
      active_from_hour: 6,
      active_to_hour: 24,
      full_charge_every_days: 7,
    });
  });

  it("règle une plage où le plancher de la batterie est plus haut", async () => {
    const home: HomeModel = {
      devices: [...HOME.devices, { key: "battery", kind: "Battery", name: "Batterie", sensors: [], capacity_kwh: 5 }],
    };
    const [sent, put] = recording();
    mockApi(put, { home });
    renderHome();

    const sheet = await openSheet("L'essentiel", /^Batterie/, "Batterie");
    await userEvent.click(within(sheet).getByRole("button", { name: "Ajouter une plage où le plancher est plus haut" }));
    const percent = within(sheet).getByRole("listitem", { name: "Plage de plancher 1" }).querySelector("input")!;
    await userEvent.tripleClick(percent);
    await userEvent.keyboard("30");
    await save(sheet);

    await saved();
    expect(sent[0].battery!.floor_ranges).toEqual([{ start_hour: 0, end_hour: 6, percent: 30 }]);
  });

  it("n'affiche pas la batterie d'une maison qui n'en a pas", async () => {
    mockApi();
    renderHome();

    await screen.findByRole("button", { name: /^Mon contrat/ });
    expect(screen.queryByRole("button", { name: /^Batterie/ })).toBeNull();
  });

  it("règle les panneaux de chaque installation solaire", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    const sheet = await openSheet("L'essentiel", /^Panneaux/, "Panneaux");
    await userEvent.click(within(sheet).getByRole("button", { name: "Décrire les panneaux" }));
    await save(sheet);

    await saved();
    const solar = sent[0].devices.find((d) => d.key === "solar")!;
    expect(solar.default).toBe(false);
    expect(solar.panels?.arrays.length).toBeGreaterThan(0);
  });

  it("règle les règles d'un cycle : démarre après, report toléré", async () => {
    const home: HomeModel = {
      devices: [
        { key: "washer", kind: "WashingMachine", name: "Lave-linge", sensors: [], capacity_kwh: null },
        { key: "dryer", kind: "Dryer", name: "Sèche-linge", sensors: [], capacity_kwh: null },
      ],
    };
    const configuration: Configuration = {
      version: 1,
      devices: home.devices.map((d) => ({
        key: d.key,
        behavior: "CycleBehavior",
        automation: "RecommendAutomation",
        planned: true,
        default: true,
      })),
      tariff: null,
    };
    const [sent, put] = recording();
    mockApi(put, { home, configuration });
    renderHome();

    const sheet = await openSheet("Appareils", /^Sèche-linge/, "Sèche-linge");
    const dryer = within(sheet).getByRole("group", { name: "Règles du cycle de Sèche-linge" });
    const select = within(dryer).getByLabelText("Démarre après la fin de") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["aucun équipement", "Lave-linge"]);
    await userEvent.selectOptions(select, "washer");
    await userEvent.type(within(dryer).getByLabelText(/Peut être reporté de/), "1");
    await save(sheet);

    await saved();
    expect(sent[0].devices.find((d) => d.key === "dryer")).toMatchObject({ after: "washer", max_delay_days: 1 });
    expect(sent[0].devices.find((d) => d.key === "washer")!.after).toBeUndefined(); // inchangé
  });

  it("règle la récurrence d'un cycle", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    const sheet = await openSheet("Appareils", /^Lave-linge/, "Lave-linge");
    const washer = within(sheet).getByRole("group", { name: "Règles du cycle de Lave-linge" });
    await userEvent.selectOptions(within(washer).getByLabelText("Revient"), "weekly");
    await userEvent.click(within(washer).getByLabelText("mar."));
    await userEvent.click(within(washer).getByLabelText("ven."));
    await userEvent.click(within(washer).getByLabelText("lun.")); // coché par défaut
    expect(washer).toHaveTextContent("Les tâches récurrentes de Home Assistant pour cet équipement sont alors ignorées");
    await save(sheet);

    await saved();
    expect(sent[0].devices.find((d) => d.key === "washer")!.recurrence).toEqual({ rule: "FREQ=WEEKLY;BYDAY=TU,FR" });
  });

  it("reprend et enregistre les règles des descriptions des tâches de HA", async () => {
    const [sent, put] = recording();
    mockApi(put, {
      other: (url) =>
        url === "api/configuration/task-rules-proposal"
          ? Response.json([{ key: "washer", recurrence: { rule: "FREQ=DAILY;INTERVAL=2", start: "2026-10-12" }, after: null }])
          : undefined,
    });
    renderHome();

    await userEvent.click(await screen.findByRole("tab", { name: "Avancé" }));
    await userEvent.click(await screen.findByRole("button", { name: "Reprendre les règles des tâches de Home Assistant" }));

    expect(await screen.findByText(/Règles reprises des descriptions des tâches et enregistrées/)).toBeInTheDocument();
    expect(sent[0].devices.find((d) => d.key === "washer")).toMatchObject({
      default: false,
      recurrence: { rule: "FREQ=DAILY;INTERVAL=2", start: "2026-10-12" },
    });
    const sheet = await openSheet("Appareils", /^Lave-linge/, "Lave-linge");
    const washer = within(sheet).getByRole("group", { name: "Règles du cycle de Lave-linge" });
    expect(within(washer).getByLabelText("Revient")).toHaveValue("daily");
    expect(within(washer).getByLabelText(/^tous les/)).toHaveValue(2);
  });

  it("choisit l'objectif du calcul, préréglage ou poids libres", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    let sheet = await openSheet("L'essentiel", /^Ma priorité/, "Objectif du calcul");
    const preset = within(sheet).getByLabelText("Le calcul vise");
    expect(within(sheet).getByText("Aucun objectif réglé : le coût d'abord.")).toBeInTheDocument();
    expect([...(preset as HTMLSelectElement).options].map((o) => o.value)).toEqual([
      "cost",
      "autonomy",
      "self_consumption",
    ]); // poids libres cachés tant qu'on ne les demande pas
    await userEvent.selectOptions(preset, "self_consumption");
    await save(sheet);
    await saved();
    expect(sent[0].objective).toEqual({ preset: "self_consumption", weights: null, co2_entity: null });

    sheet = await openSheet("L'essentiel", /^Ma priorité/, "Objectif du calcul");
    const exportWeight = within(within(sheet).getByRole("group", { name: "Poids des critères" })).getByLabelText(
      "Surplus envoyé au réseau",
    );
    await userEvent.tripleClick(exportWeight);
    await userEvent.keyboard("1");
    await save(sheet);
    await saved();
    expect(sent[1].objective).toEqual({
      preset: "custom",
      weights: { cost: 1, grid_import: 0, grid_export: 1 },
      co2_entity: null,
    });

    // CO₂ : proposé seulement avec une entité d'intensité du réseau.
    sheet = await openSheet("L'essentiel", /^Ma priorité/, "Objectif du calcul");
    await userEvent.type(within(sheet).getByLabelText(/Intensité carbone du réseau/), "sensor.co2");
    await userEvent.selectOptions(within(sheet).getByLabelText("Le calcul vise"), "co2");
    await save(sheet);
    await saved();
    expect(sent[2].objective).toEqual({ preset: "co2", weights: null, co2_entity: "sensor.co2" });
  }, 15_000);

  it("règle les vitesses et les durées de la filtration", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    const sheet = await openSheet("Appareils", /^Piscine/, "Piscine");
    const pool = within(sheet).getByRole("group", { name: "Durée de fonctionnement de Piscine" });
    expect(pool).toHaveTextContent("Aucune vitesse réglée");
    const add = within(sheet).getByRole("button", { name: "Ajouter une vitesse" });
    await userEvent.click(add);
    await userEvent.click(add);
    const [first, second] = [1, 2].map((n) => within(sheet).getByRole("listitem", { name: `Vitesse ${n}` }));
    for (const [item, name, kw] of [
      [first, "silence", "0.13"],
      [second, "eco", "0.415"],
    ] as const) {
      const [nameInput, power] = item.querySelectorAll("input");
      await userEvent.type(nameInput, name);
      await userEvent.clear(power);
      await userEvent.type(power, kw);
    }
    await save(sheet);

    await saved();
    const pump = sent[0].devices.find((d) => d.key === "pool")!;
    expect(pump.default).toBe(false);
    expect(pump.runtime).toEqual({
      speeds: [
        { name: "silence", kw: 0.13 },
        { name: "eco", kw: 0.415 },
      ],
      minimum_hours: { summer: 2, mid_season: 1, winter: 0 },
      skip_days: { summer: 1, mid_season: 2, winter: 365 },
      max_starts: 2,
    });
  });

  it("règle le besoin d'énergie d'un véhicule suivi seulement", async () => {
    const home: HomeModel = {
      devices: [{ key: "car", kind: "OtherLoad", name: "Voiture", sensors: [], capacity_kwh: null }],
    };
    const configuration: Configuration = {
      version: 1,
      devices: [{ key: "car", behavior: "UncontrolledBehavior", automation: "InformAutomation", planned: true, default: true }],
      tariff: null,
    };
    const [sent, put] = recording();
    mockApi(put, { home, configuration });
    renderHome();

    // Suivi seulement : dans le groupe replié.
    await userEvent.click(await screen.findByRole("tab", { name: "Appareils" }));
    await userEvent.click(screen.getByText("Voiture", { selector: "summary .ui-row-label" }));
    await userEvent.click(screen.getByRole("button", { name: "Voiture" }));
    const sheet = screen.getByRole("dialog", { name: "Voiture" });
    await userEvent.selectOptions(within(sheet).getByLabelText("Comportement"), "EnergyByDeadlineBehavior");
    const need = within(sheet).getByRole("group", { name: "Besoin d'énergie de Voiture" });
    expect(need).toHaveTextContent("Aucun besoin réglé");
    for (const [label, value] of [
      ["Énergie à fournir", "30"],
      ["Puissance maximale", "7"],
    ] as const) {
      const input = within(sheet).getByLabelText(label);
      await userEvent.clear(input);
      await userEvent.type(input, value);
    }
    await userEvent.click(within(sheet).getByLabelText(/Par paliers/));
    await userEvent.click(within(sheet).getByLabelText(/Chaque jour/));
    await save(sheet);

    await saved();
    expect(sent[0].devices[0].energy).toEqual({
      energy_kwh: 30,
      earliest_hour: 0,
      deadline_hour: 7,
      max_kw: 7,
      steps: true,
      daily: false,
    });
  });

  it("règle les contraintes horaires d'un équipement placé", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    const sheet = await openSheet("Appareils", /^Lave-linge/, "Lave-linge");
    const washer = within(sheet).getByRole("group", { name: "Contraintes horaires de Lave-linge" });
    expect(washer).toHaveTextContent("Aucune contrainte");
    const inWasher = (name: string) => [...washer.querySelectorAll("button")].find((b) => b.textContent === name)!;
    await userEvent.click(inWasher("Ajouter une plage interdite"));
    await userEvent.click(inWasher("Ajouter « terminé avant »"));
    const second = within(sheet).getByRole("listitem", { name: "Contrainte 2" });
    const before = second.querySelector("input[type=number]")!;
    await userEvent.tripleClick(before); // champ vidé : il reprend son minimum
    await userEvent.keyboard("17");
    await userEvent.click(second.querySelector("input[type=checkbox]")!);
    await save(sheet);

    await saved();
    expect(sent[0].devices.find((d) => d.key === "washer")!.constraints).toEqual([
      { kind: "forbidden", start_hour: 22, end_hour: 7, hard: true },
      { kind: "finish_before", start_hour: 0, end_hour: 17, hard: false },
    ]);
  });

  it("commence par les appareils proposés quand la maison n'est pas encore enregistrée", async () => {
    mockApi(undefined, {
      home: { devices: [] },
      configuration: { version: 1, devices: [], tariff: null },
      other: (url) =>
        url.startsWith("api/home/proposals")
          ? Response.json({
              energy_dashboard: true,
              devices: [{ key: "washer", kind: "WashingMachine", name: "Lave-linge", sensors: [], capacity_kwh: null, issues: [] }],
            })
          : undefined,
    });
    renderHome();

    expect(await screen.findByText(/Voici ce que l'application a reconnu/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Appareils" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("article", { name: "Lave-linge" })).toBeInTheDocument();
  });

  it("ne déplie rien pour des réglages par défaut, qui s'enregistrent tels quels (lot 4.7)", async () => {
    const [sent, put] = recording();
    mockApi(put);
    renderHome();

    const sheet = await openSheet("Appareils", /^Piscine/, "Piscine");
    expect(sheet.querySelectorAll("details").length).toBeGreaterThan(0);
    expect(sheet.querySelectorAll("details[open]")).toHaveLength(0);
    await save(sheet);
    await saved();
    expect(sent).toHaveLength(0); // rien de changé : rien d'envoyé
  });

  it("ouvre les réglages avancés qui ne sont plus ceux par défaut", async () => {
    const speeds = [{ name: "eco", kw: 0.4 }];
    mockApi(undefined, {
      configuration: {
        ...CONFIGURATION,
        devices: CONFIGURATION.devices.map((d) =>
          d.key === "pool" ? { ...d, default: false, runtime: { ...DEFAULT_RUNTIME, speeds } } : d,
        ),
      },
    });
    renderHome();

    const sheet = await openSheet("Appareils", /^Piscine/, "Piscine");
    const pool = within(sheet).getByRole("group", { name: "Durée de fonctionnement de Piscine" });
    expect(pool.querySelector("details")?.open).toBe(true);
    expect(within(pool).getByText("Réglages avancés (modifiés)")).toBeInTheDocument();
    expect(sheet.querySelectorAll("details[open]")).toHaveLength(1);
  });
});
