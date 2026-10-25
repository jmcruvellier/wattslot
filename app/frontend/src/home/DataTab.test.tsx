// Onglet « Données » de Ma maison (qualité des données) : résumé, corrections, trous, feuille
// d'une correction, analyse d'une période.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import type { Correction } from "./DataTab";
import DataTab from "./DataTab";
import type { HomeData } from "./HomeSummary";

const DATA: HomeData = {
  devices: [
    {
      key: "grid",
      kind: "GridConnection",
      name: "Réseau",
      capacity_kwh: null,
      sensors: [
        { entity_id: "sensor.grid_off_peak", role: "EnergyImported", resets_daily: false },
        { entity_id: "sensor.grid_peak", role: "EnergyImported", resets_daily: false },
      ],
    },
    {
      key: "fridge",
      kind: "OtherLoad",
      name: "Frigo",
      capacity_kwh: null,
      sensors: [
        { entity_id: "sensor.fridge_energy", role: "EnergyConsumed", resets_daily: false },
        { entity_id: "sensor.fridge_power", role: "PowerConsumed", resets_daily: false },
      ],
    },
  ],
  configuration: { version: 1, devices: [], tariff: null },
};

const START = "2026-10-19T22:00:00Z"; // 20/10 à minuit à Paris

function correction(change: Partial<Correction>): Correction {
  return {
    id: 1,
    entity_id: "sensor.grid_off_peak",
    period: "PT1H",
    start: START,
    kind: "spike",
    method: "raw",
    original_kwh: 23147.73,
    corrected_kwh: 0.12,
    automatic: true,
    created_at: "2026-10-20T08:00:00Z",
    undone_at: null,
    ...change,
  };
}

type Call = { url: string; method: string; body: unknown };

function mockApi(corrections: Correction[], respond: (call: Call) => Response | undefined = () => undefined) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const call = {
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body ? (JSON.parse(String(init.body)) as unknown) : null,
    };
    calls.push(call);
    const answer = respond(call);
    if (answer) return answer;
    if (call.url.startsWith("api/quality/corrections") && call.method === "GET") return Response.json(corrections);
    if (call.url === "api/quality/status") return Response.json({ running: true, last_run_at: "2026-10-20T08:15:00Z" });
    if (call.url === "api/quality/scan") {
      return Response.json({
        anomalies: [
          { entity_id: "sensor.fridge_energy", device: "fridge", period: "PT1H", start: "2026-10-18T10:00:00Z", kind: "gap", energy_kwh: null, missing: 2, correction: null },
          { entity_id: "sensor.fridge_energy", device: "fridge", period: "PT1H", start: "2026-10-18T20:00:00Z", kind: "gap", energy_kwh: null, missing: 1, correction: null },
        ],
        corrected: 0,
      });
    }
    return new Response(null, { status: 404 });
  });
  return calls;
}

function renderTab() {
  return render(
    <I18nProvider>
      <DataTab data={DATA} />
    </I18nProvider>,
  );
}

describe("onglet Données", () => {
  beforeEach(() => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("résume les corrections, nomme le compteur et regroupe les trous", async () => {
    mockApi([correction({}), correction({ id: 2, undone_at: "2026-10-20T09:00:00Z" })]);
    renderTab();

    expect(await screen.findByText("1 valeur(s) corrigée(s)")).toBeInTheDocument();
    const [row] = screen.getAllByRole("button", { name: /^Réseau · sensor.grid_off_peak/ }); // l'autre : annulée
    // Période dans l'heure du navigateur : la CI tourne en UTC, la maison à Paris.
    const from = new Date(START);
    const time = (d: Date) => d.toLocaleTimeString("fr", { hour: "2-digit", minute: "2-digit" });
    const day = from.toLocaleDateString("fr", { day: "2-digit", month: "2-digit" });
    const to = new Date(from.getTime() + 3_600_000);
    expect(row).toHaveTextContent(`${day}, ${time(from)} – ${time(to)} · 23148 kWh → 0,12 kWh`);
    expect(screen.getByText("Frigo")).toBeInTheDocument(); // un seul compteur : le nom seul
    expect(screen.getByText("3 h sans valeur depuis le 18/10")).toBeInTheDocument();
    expect(screen.getByText("Corrections annulées (1)").closest("details")!.open).toBe(false);
  });

  it("montre une heure et son quart d'heure sur une seule ligne, et les corrige ensemble", async () => {
    const quarter = correction({ id: 5, period: "PT15M", start: "2026-10-19T22:00:00Z", corrected_kwh: 0.1 });
    const calls = mockApi([correction({}), quarter], (call) =>
      call.method === "POST" && call.url === "api/quality/corrections" ? Response.json({}, { status: 201 }) : undefined,
    );
    renderTab();

    expect(await screen.findByText("1 valeur(s) corrigée(s)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Réseau/ }));
    const sheet = screen.getByRole("dialog");
    expect(sheet).toHaveTextContent(/Avec le quart d'heure .* : 23148 kWh → 0,10 kWh/);
    await userEvent.click(within(sheet).getByRole("button", { name: "Écarter" }));

    const posted = calls.filter((c) => c.method === "POST" && c.url === "api/quality/corrections");
    expect(posted.map((c) => (c.body as { period: string }).period)).toEqual(["PT1H", "PT15M"]);
  });

  it("dit quand les données sont saines", async () => {
    mockApi([]);
    renderTab();

    expect(await screen.findByText("Vos données sont saines")).toBeInTheDocument();
  });

  it("explique une correction et en propose une autre", async () => {
    const calls = mockApi([correction({})], (call) =>
      call.method === "POST" && call.url === "api/quality/corrections"
        ? Response.json({ detail: "no_raw" }, { status: 422 })
        : undefined,
    );
    renderTab();
    await userEvent.click(await screen.findByRole("button", { name: /^Réseau/ }));
    const sheet = screen.getByRole("dialog", { name: "Réseau · sensor.grid_off_peak" });

    expect(sheet).toHaveTextContent("23148 kWh comptés : plus que la maison ne peut tirer.");
    expect(sheet).toHaveTextContent("Corrigée automatiquement. Recalculée sur le relevé brut : 0,12 kWh.");
    // L'aide dit ce que fait chaque correction, et son effet sur le trou des courbes.
    expect(sheet).toHaveTextContent("l'un ou l'autre comble le trou dans les courbes du jour");
    // La méthode en vigueur n'est pas reproposée.
    expect(within(sheet).queryByRole("button", { name: "Recalculer depuis le brut" })).toBeNull();
    await userEvent.click(within(sheet).getByRole("button", { name: "Estimer" }));

    expect(calls.at(-1)).toMatchObject({
      method: "POST",
      body: { entity_id: "sensor.grid_off_peak", period: "PT1H", start: START, method: "estimate" },
    });
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("n'est plus gardé");
  });

  it("annule une correction et relit l'onglet", async () => {
    const calls = mockApi([correction({ method: "discard", corrected_kwh: null, automatic: false })], (call) =>
      call.method === "DELETE" ? new Response(null, { status: 204 }) : undefined,
    );
    renderTab();
    await userEvent.click(await screen.findByRole("button", { name: /écartée/ }));
    const sheet = screen.getByRole("dialog");
    expect(sheet).toHaveTextContent("Corrigée à la main. Écartée : le calcul l'ignore et la courbe garde un trou à cette heure.");

    await userEvent.click(within(sheet).getByRole("button", { name: "Annuler la correction" }));

    expect(calls.some((c) => c.method === "DELETE" && c.url === "api/quality/corrections/1")).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.filter((c) => c.url === "api/quality/status")).toHaveLength(2); // relu
  });

  it("analyse une période pour un compteur", async () => {
    const calls = mockApi([]);
    renderTab();
    await userEvent.click(await screen.findByRole("button", { name: "Analyser une période" }));
    const sheet = screen.getByRole("dialog", { name: "Analyser une période" });
    const sensor = within(sheet).getByLabelText("Compteur") as HTMLSelectElement;
    expect([...sensor.options].map((o) => o.textContent)).toEqual([
      "Tous les compteurs",
      "Réseau · sensor.grid_off_peak",
      "Réseau · sensor.grid_peak",
      "Frigo",
    ]);
    await userEvent.selectOptions(sensor, "sensor.fridge_energy");
    await userEvent.click(within(sheet).getByRole("button", { name: "Analyser" }));

    expect(await within(sheet).findByRole("status")).toHaveTextContent("Aucune anomalie sur cette période.");
    const scans = calls.filter((c) => c.url === "api/quality/scan").map((c) => c.body);
    expect(scans).toContainEqual(expect.objectContaining({ entity_ids: ["sensor.fridge_energy"] }));
  });
});
