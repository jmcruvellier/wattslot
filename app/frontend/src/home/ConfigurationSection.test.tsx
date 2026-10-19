import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import ConfigurationSection from "./ConfigurationSection";
import { DEFAULT_RUNTIME, type Configuration } from "./configuration";
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

function mockApi(put: (body: Configuration) => Response) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/home") return Response.json(HOME);
    if (url === "api/configuration" && init?.method === "PUT") {
      return put(JSON.parse(String(init.body)) as Configuration);
    }
    if (url === "api/configuration") return Response.json(CONFIGURATION);
    return new Response(null, { status: 404 });
  });
}

function renderSection() {
  return render(
    <I18nProvider>
      <ConfigurationSection version={0} onNavigate={vi.fn()} />
    </I18nProvider>,
  );
}

describe("ConfigurationSection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("propose les comportements du type et enregistre les choix", async () => {
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json({ ...body, devices: body.devices.map((d) => ({ ...d, default: false })) });
    });
    renderSection();

    const pool = await screen.findByRole("article", { name: "Piscine" });
    const select = pool.querySelector("select")!;
    expect([...select.options].map((o) => o.textContent)).toEqual([
      "Durée de fonctionnement à placer",
      "Consommation seulement suivie",
    ]);
    // Production : un seul comportement, ni case « pris en compte ».
    const solar = screen.getByRole("article", { name: "Panneaux" });
    expect(solar.querySelector("select")!.disabled).toBe(true);
    expect(solar.querySelector("input[type=checkbox]")).toBeNull();

    await userEvent.click(screen.getByRole("article", { name: "Lave-linge" }).querySelector("input")!);
    await userEvent.selectOptions(select, "UncontrolledBehavior");
    expect(pool.querySelector("input[type=checkbox]")).toBeNull(); // non pilotable : rien à placer
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Réglages enregistrés.");
    const devices = Object.fromEntries(sent[0].devices.map((d) => [d.key, d]));
    expect(devices.washer).toMatchObject({ planned: false, default: false });
    expect(devices.pool).toMatchObject({
      behavior: "UncontrolledBehavior",
      automation: "InformAutomation",
      default: false,
    });
    expect(devices.solar.default).toBe(true); // inchangé : pas enregistré
  });

  it("affiche les anomalies renvoyées par l'API", async () => {
    mockApi(() =>
      Response.json(
        { detail: [{ code: "behavior_not_allowed", device: "pool", params: {} }] },
        { status: 422 },
      ),
    );
    renderSection();

    await screen.findByRole("article", { name: "Piscine" });
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Piscine : comportement impossible pour ce type d'équipement.",
    );
  });

  it("règle le tarif : heures creuses et pleines, revente, retour au prix par défaut", async () => {
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json(body);
    });
    renderSection();

    expect(await screen.findByText(/prix unique de 0.25\s€\/kWh/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Définir des heures creuses et pleines" }));
    const base = screen.getByLabelText(/Prix hors des plages/);
    await userEvent.clear(base);
    await userEvent.type(base, "0.179076");
    const night = screen.getByRole("listitem", { name: "Plage 1" });
    const nightPrice = night.querySelector("input")!;
    await userEvent.clear(nightPrice);
    await userEvent.type(nightPrice, "0.138252");
    await userEvent.click(screen.getByRole("button", { name: "Ajouter une plage" }));
    await userEvent.click(screen.getByRole("listitem", { name: "Plage 3" }).querySelector("button")!);
    const subscription = screen.getByLabelText(/Abonnement/);
    await userEvent.clear(subscription);
    await userEvent.type(subscription, "15.5");
    await userEvent.type(screen.getByLabelText(/Puissance souscrite/), "9");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Réglages enregistrés.");
    expect(sent[0].tariff).toEqual({
      kind: "TimeOfUseTariff",
      base_eur_kwh: 0.179076,
      bands: [
        { start_hour: 0, end_hour: 6, eur_kwh: 0.138252, weekdays: [], months: [] },
        { start_hour: 22, end_hour: 24, eur_kwh: 0.15, weekdays: [], months: [] },
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

    await userEvent.click(screen.getByRole("button", { name: "Revenir au prix par défaut" }));
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));
    expect(sent[1].tariff).toBeNull();
  });

  it("règle un tarif Tempo et un prix dynamique", async () => {
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json(body);
    });
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Définir un tarif par couleur de jour (Tempo)" }));
    await userEvent.type(screen.getByLabelText("Capteur de la couleur du jour"), "sensor.tempo_today");
    const red = screen.getByRole("group", { name: "Couleur Rouge" });
    const redPrice = red.querySelector("input[type=number]")!;
    await userEvent.clear(redPrice);
    await userEvent.type(redPrice, "0.7562");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
    const tempo = sent[0].tariff!;
    expect(tempo.kind).toBe("DayColorTariff");
    expect(tempo.color_entity).toBe("sensor.tempo_today");
    expect(tempo.color_day_start_hour).toBe(6);
    expect(tempo.colors.map((c) => [c.color, c.base_eur_kwh])).toEqual([
      ["Bleu", 0.16],
      ["Blanc", 0.19],
      ["Rouge", 0.7562],
    ]);

    await userEvent.selectOptions(screen.getByLabelText("Type de tarif"), "DynamicTariff");
    await userEvent.type(screen.getByLabelText("Capteur du prix"), "sensor.nordpool");
    await userEvent.selectOptions(screen.getByLabelText("Unité des prix lus dans Home Assistant"), "0.001");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].tariff).toMatchObject({ kind: "DynamicTariff", price_entity: "sensor.nordpool", price_factor: 0.001 });
  }, 15_000); // beaucoup de saisie : plus de 5 s quand toute la suite tourne en parallèle

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
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home") return Response.json(HOME);
      if (url === "api/configuration") return Response.json(CONFIGURATION);
      if (url === "api/configuration/tariff-proposal") return Response.json(proposal);
      return new Response(null, { status: 404 });
    });
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Proposer d'après le tableau Énergie" }));

    expect(await screen.findByLabelText("Capteur du prix")).toHaveValue("sensor.spot");
    expect(screen.getByLabelText("Type de tarif")).toHaveValue("DynamicTariff");
  });

  it("signale un tableau Énergie sans prix ou un Home Assistant absent", async () => {
    let status = 200;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home") return Response.json(HOME);
      if (url === "api/configuration") return Response.json(CONFIGURATION);
      return status === 200 ? Response.json(null) : new Response(null, { status });
    });
    renderSection();

    const button = await screen.findByRole("button", { name: "Proposer d'après le tableau Énergie" });
    await userEvent.click(button);
    expect(await screen.findByRole("status")).toHaveTextContent("ne déclare aucun prix");
    status = 503;
    await userEvent.click(button);
    expect(await screen.findByText(/Home Assistant n'est pas connecté/)).toBeInTheDocument();
  });

  it("règle la batterie quand la maison en a une", async () => {
    const withBattery: HomeModel = {
      devices: [...HOME.devices, { key: "battery", kind: "Battery", name: "Batterie", sensors: [], capacity_kwh: 5.12 }],
    };
    const sent: Configuration[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "api/home") return Response.json(withBattery);
      if (url === "api/configuration" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as Configuration;
        sent.push(body);
        return Response.json(body);
      }
      if (url === "api/configuration") return Response.json(CONFIGURATION);
      return new Response(null, { status: 404 });
    });
    renderSection();

    const charge = await screen.findByLabelText(/Puissance de charge maximale/);
    expect(charge).toHaveAttribute("placeholder", "2560"); // 0,5 C de 5,12 kWh
    expect(screen.getByText(/Réglages par défaut : modifiez-les/)).toBeInTheDocument();
    await userEvent.type(charge, "2500");
    await userEvent.type(screen.getByLabelText(/Puissance de décharge maximale/), "800");
    const floor = screen.getByLabelText(/Ne jamais décharger en dessous de/);
    await userEvent.clear(floor);
    await userEvent.type(floor, "12");
    await userEvent.selectOptions(screen.getAllByLabelText("de")[0], "6");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
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
    const withBattery: HomeModel = {
      devices: [...HOME.devices, { key: "battery", kind: "Battery", name: "Batterie", sensors: [], capacity_kwh: 5 }],
    };
    const sent: Configuration[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input) === "api/home") return Response.json(withBattery);
      if (init?.method === "PUT") {
        sent.push(JSON.parse(String(init.body)) as Configuration);
        return Response.json(sent[0]);
      }
      return Response.json(CONFIGURATION);
    });
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Ajouter une plage où le plancher est plus haut" }));
    const range = screen.getByRole("listitem", { name: "Plage de plancher 1" });
    const percent = range.querySelector("input")!;
    await userEvent.tripleClick(percent);
    await userEvent.keyboard("30");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
    expect(sent[0].battery!.floor_ranges).toEqual([{ start_hour: 0, end_hour: 6, percent: 30 }]);
  });

  it("règle les règles d'un cycle : démarre après, report toléré", async () => {
    const home: HomeModel = {
      devices: [
        { key: "washer", kind: "WashingMachine", name: "Lave-linge", sensors: [], capacity_kwh: null },
        { key: "dryer", kind: "Dryer", name: "Sèche-linge", sensors: [], capacity_kwh: null },
      ],
    };
    const sent: Configuration[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input) === "api/home") return Response.json(home);
      if (init?.method === "PUT") {
        sent.push(JSON.parse(String(init.body)) as Configuration);
        return Response.json(sent[0]);
      }
      return Response.json({
        version: 1,
        devices: home.devices.map((d) => ({
          key: d.key,
          behavior: "CycleBehavior",
          automation: "RecommendAutomation",
          planned: true,
          default: true,
        })),
        tariff: null,
      });
    });
    renderSection();

    const dryer = await screen.findByRole("group", { name: "Règles du cycle de Sèche-linge" });
    const select = within(dryer).getByLabelText("Démarre après la fin de") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["aucun équipement", "Lave-linge"]);
    await userEvent.selectOptions(select, "washer");
    await userEvent.type(within(dryer).getByLabelText(/Peut être reporté de/), "1");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
    expect(sent[0].devices.find((d) => d.key === "dryer")).toMatchObject({ after: "washer", max_delay_days: 1 });
    expect(sent[0].devices.find((d) => d.key === "washer")!.after).toBeUndefined(); // inchangé
  });

  it("règle la récurrence d'un cycle", async () => {
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json(body);
    });
    renderSection();

    const washer = await screen.findByRole("group", { name: "Règles du cycle de Lave-linge" });
    await userEvent.selectOptions(within(washer).getByLabelText("Revient"), "weekly");
    await userEvent.click(within(washer).getByLabelText("mar."));
    await userEvent.click(within(washer).getByLabelText("ven."));
    await userEvent.click(within(washer).getByLabelText("lun.")); // coché par défaut
    expect(washer).toHaveTextContent("Les tâches récurrentes de Home Assistant pour cet équipement sont alors ignorées");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
    expect(sent[0].devices.find((d) => d.key === "washer")!.recurrence).toEqual({ rule: "FREQ=WEEKLY;BYDAY=TU,FR" });
  });

  it("reprend les règles des descriptions des tâches de HA", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home") return Response.json(HOME);
      if (url === "api/configuration/task-rules-proposal") {
        return Response.json([
          { key: "washer", recurrence: { rule: "FREQ=DAILY;INTERVAL=2", start: "2026-10-12" }, after: null },
        ]);
      }
      return Response.json(CONFIGURATION);
    });
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Reprendre les règles des tâches de Home Assistant" }));

    expect(await screen.findByText(/Règles reprises des descriptions des tâches/)).toBeInTheDocument();
    const washer = screen.getByRole("group", { name: "Règles du cycle de Lave-linge" });
    expect(within(washer).getByLabelText("Revient")).toHaveValue("daily");
    expect(within(washer).getByLabelText(/^tous les/)).toHaveValue(2);
  });

  it("choisit l'objectif du calcul, préréglage ou poids libres", async () => {
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json(body);
    });
    renderSection();

    const preset = await screen.findByLabelText("Le calcul vise");
    expect(screen.getByText("Aucun objectif réglé : le coût d'abord.")).toBeInTheDocument();
    expect([...(preset as HTMLSelectElement).options].map((o) => o.value)).toEqual([
      "cost",
      "autonomy",
      "self_consumption",
    ]); // poids libres cachés tant qu'on ne les demande pas
    await userEvent.selectOptions(preset, "self_consumption");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));
    await screen.findByRole("status");
    expect(sent[0].objective).toEqual({ preset: "self_consumption", weights: null, co2_entity: null });

    const exportWeight = within(screen.getByRole("group", { name: "Poids des critères" })).getByLabelText("Surplus envoyé au réseau");
    await userEvent.tripleClick(exportWeight);
    await userEvent.keyboard("1");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));
    await screen.findByText("Réglages enregistrés.");
    expect(sent[1].objective).toEqual({
      preset: "custom",
      weights: { cost: 1, grid_import: 0, grid_export: 1 },
      co2_entity: null,
    });

    // CO₂ : proposé seulement avec une entité d'intensité du réseau.
    await userEvent.type(screen.getByLabelText(/Intensité carbone du réseau/), "sensor.co2");
    await userEvent.selectOptions(screen.getByLabelText("Le calcul vise"), "co2");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));
    await screen.findByText("Réglages enregistrés.");
    expect(sent[2].objective).toEqual({ preset: "co2", weights: null, co2_entity: "sensor.co2" });
  });

  it("n'affiche pas la batterie d'une maison qui n'en a pas", async () => {
    mockApi((body) => Response.json(body));
    renderSection();

    await screen.findByRole("article", { name: "Piscine" });
    expect(screen.queryByText("Batterie")).toBeNull();
  });

  it("règle les vitesses et les durées de la filtration", async () => {
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json(body);
    });
    renderSection();

    const pool = await screen.findByRole("group", { name: "Durée de fonctionnement de Piscine" });
    expect(pool).toHaveTextContent("Aucune vitesse réglée");
    const add = screen.getByRole("button", { name: "Ajouter une vitesse" });
    await userEvent.click(add);
    await userEvent.click(add);
    const [first, second] = [1, 2].map((n) => screen.getByRole("listitem", { name: `Vitesse ${n}` }));
    for (const [item, name, kw] of [
      [first, "silence", "0.13"],
      [second, "eco", "0.415"],
    ] as const) {
      const [nameInput, power] = item.querySelectorAll("input");
      await userEvent.type(nameInput, name);
      await userEvent.clear(power);
      await userEvent.type(power, kw);
    }
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
    const saved = sent[0].devices.find((d) => d.key === "pool")!;
    expect(saved.default).toBe(false);
    expect(saved.runtime).toEqual({
      speeds: [
        { name: "silence", kw: 0.13 },
        { name: "eco", kw: 0.415 },
      ],
      minimum_hours: { summer: 2, mid_season: 1, winter: 0 },
      skip_days: { summer: 1, mid_season: 2, winter: 365 },
      max_starts: 2,
    });
  });

  it("règle le besoin d'énergie d'un véhicule", async () => {
    const sent: Configuration[] = [];
    const home: HomeModel = {
      devices: [{ key: "car", kind: "OtherLoad", name: "Voiture", sensors: [], capacity_kwh: null }],
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input) === "api/home") return Response.json(home);
      if (init?.method === "PUT") {
        sent.push(JSON.parse(String(init.body)) as Configuration);
        return Response.json(sent[0]);
      }
      return Response.json({
        version: 1,
        devices: [{ key: "car", behavior: "UncontrolledBehavior", automation: "InformAutomation", planned: true, default: true }],
        tariff: null,
      });
    });
    renderSection();

    const car = await screen.findByRole("article", { name: "Voiture" });
    await userEvent.selectOptions(car.querySelector("select")!, "EnergyByDeadlineBehavior");
    const need = screen.getByRole("group", { name: "Besoin d'énergie de Voiture" });
    expect(need).toHaveTextContent("Aucun besoin réglé");
    for (const [label, value] of [
      ["Énergie à fournir", "30"],
      ["Puissance maximale", "7"],
    ] as const) {
      const input = screen.getByLabelText(label);
      await userEvent.clear(input);
      await userEvent.type(input, value);
    }
    await userEvent.click(screen.getByLabelText(/Par paliers/));
    await userEvent.click(screen.getByLabelText(/Chaque jour/));
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
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
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json(body);
    });
    renderSection();

    const washer = await screen.findByRole("group", { name: "Contraintes horaires de Lave-linge" });
    expect(washer).toHaveTextContent("Aucune contrainte");
    expect(screen.queryByRole("group", { name: "Contraintes horaires de Panneaux" })).toBeNull();
    const inWasher = (name: string) =>
      [...washer.querySelectorAll("button")].find((b) => b.textContent === name)!;
    await userEvent.click(inWasher("Ajouter une plage interdite"));
    await userEvent.click(inWasher("Ajouter « terminé avant »"));
    const second = screen.getByRole("listitem", { name: "Contrainte 2" });
    const before = second.querySelector("input[type=number]")!;
    await userEvent.tripleClick(before); // champ vidé : il reprend son minimum
    await userEvent.keyboard("17");
    await userEvent.click(second.querySelector("input[type=checkbox]")!);
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));

    await screen.findByRole("status");
    expect(sent[0].devices.find((d) => d.key === "washer")!.constraints).toEqual([
      { kind: "forbidden", start_hour: 22, end_hour: 7, hard: true },
      { kind: "finish_before", start_hour: 0, end_hour: 17, hard: false },
    ]);
  });

  it("invite à enregistrer la maison d'abord", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input) === "api/home"
        ? Response.json({ devices: [] })
        : Response.json({ version: 1, devices: [] }),
    );
    renderSection();

    expect(await screen.findByText(/Enregistrez d'abord votre maison/)).toBeInTheDocument();
  });
  it("ne déplie rien pour des réglages par défaut, qui s'enregistrent tels quels (lot 4.7)", async () => {
    const sent: Configuration[] = [];
    mockApi((body) => {
      sent.push(body);
      return Response.json(body);
    });
    const { container } = renderSection();

    await screen.findByLabelText("Le calcul vise");
    expect(container.querySelectorAll("details").length).toBeGreaterThan(0);
    expect(container.querySelectorAll("details[open]")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les réglages" }));
    await screen.findByText("Réglages enregistrés.");
    expect(sent[0].devices).toEqual(CONFIGURATION.devices);
  });

  it("ouvre les réglages avancés qui ne sont plus ceux par défaut", async () => {
    const speeds = [{ name: "eco", kw: 0.4 }];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home") return Response.json(HOME);
      return Response.json({
        ...CONFIGURATION,
        devices: CONFIGURATION.devices.map((d) =>
          d.key === "pool"
            ? { ...d, default: false, runtime: { ...DEFAULT_RUNTIME, speeds } }
            : d,
        ),
      });
    });
    const { container } = renderSection();

    const pool = await screen.findByRole("group", { name: "Durée de fonctionnement de Piscine" });
    const details = pool.querySelector("details");
    expect(details?.open).toBe(true);
    expect(within(pool).getByText("Réglages avancés (modifiés)")).toBeInTheDocument();
    expect(container.querySelectorAll("details[open]")).toHaveLength(1);
  });
});
