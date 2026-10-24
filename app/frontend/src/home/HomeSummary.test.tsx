// Ma maison en phrases (lot 6b.5), rangées en onglets (refonte de Ma maison).

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reveal } from "../common/reveal";
import { I18nProvider } from "../i18n/I18nProvider";
import { translate } from "../i18n/translate";
import type { Configuration, DeviceSettings, Tariff } from "./configuration";
import HomeScreen, { TAB_KEY } from "./HomeScreen";
import { cheapestRanges, deviceText, direction, tariffText } from "./summaryText";
import type { HomeModel } from "./types";

const t = (key: string, params?: Record<string, string | number>) => translate("fr", key, params);

const BLANK_TARIFF: Tariff = {
  kind: "TimeOfUseTariff",
  base_eur_kwh: 0.18,
  bands: [
    { start_hour: 0, end_hour: 6, eur_kwh: 0.14, weekdays: [], months: [] },
    { start_hour: 22, end_hour: 24, eur_kwh: 0.14, weekdays: [], months: [] },
  ],
  export_eur_kwh: 0,
  colors: [],
  color_entity: null,
  color_tomorrow_entity: null,
  color_day_start_hour: 6,
  price_entity: null,
  export_entity: null,
  price_factor: 1,
  subscription_eur_month: 0,
  contract_kva: null,
};

function settings(key: string, change: Partial<DeviceSettings>): DeviceSettings {
  return { key, behavior: "CycleBehavior", automation: "RecommendAutomation", planned: true, default: false, ...change };
}

describe("phrases de la maison", () => {
  it("réunit les heures creuses de part et d'autre de minuit", () => {
    expect(cheapestRanges(BLANK_TARIFF.bands)).toEqual([[1320, 360]]);
    expect(cheapestRanges([{ start_hour: 12, end_hour: 14, eur_kwh: 0.1, weekdays: [], months: [] }])).toEqual([[720, 840]]);
  });

  it("résume les minutes exactes et ne réunit que des plages contiguës", () => {
    const band = (start_hour: number, start_minute: number, end_hour: number, end_minute: number) =>
      ({ start_hour, start_minute, end_hour, end_minute, eur_kwh: 0.1, weekdays: [], months: [] });
    const text = (bands: Tariff["bands"]) => tariffText({ ...BLANK_TARIFF, bands }, t, "fr");
    expect(text([band(1, 30, 5, 38)])).toBe("Heures creuses 1 h 30 – 5 h 38");
    expect(text([band(1, 30, 5, 38), band(5, 38, 6, 0)])).toBe("Heures creuses 1 h 30 – 6 h");
    expect(text([band(5, 39, 6, 0), band(1, 30, 5, 38)])).toBe("Heures creuses 1 h 30 – 5 h 38, 5 h 39 – 6 h");
    expect(text([band(22, 30, 24, 0), band(0, 0, 5, 38)])).toBe("Heures creuses 22 h 30 – 5 h 38");
    expect(text([band(22, 30, 24, 0), band(0, 1, 5, 38)])).toBe("Heures creuses 0 h 01 – 5 h 38, 22 h 30 – 24 h");
    expect(text([band(22, 30, 0, 38)])).toBe("Heures creuses 22 h 30 – 0 h 38");
  });

  it("décrit chaque sorte de contrat", () => {
    expect(tariffText(BLANK_TARIFF, t, "fr")).toBe("Heures creuses 22 h – 6 h");
    expect(tariffText(null, t, "fr")).toBe("Prix unique, 0,25\u00a0€/kWh");
    expect(tariffText({ ...BLANK_TARIFF, kind: "SingleTariff" }, t, "fr")).toBe("Prix unique, 0,18\u00a0€/kWh");
    expect(tariffText({ ...BLANK_TARIFF, kind: "DayColorTariff" }, t, "fr")).toBe("Prix selon la couleur du jour");
    expect(tariffText({ ...BLANK_TARIFF, kind: "DynamicTariff" }, t, "fr")).toBe("Prix qui change chaque heure");
  });

  it("ramène une orientation à un point cardinal", () => {
    expect([180, 90, 135, 0, 350, 270].map(direction)).toEqual(["south", "east", "south_east", "north", "north", "west"]);
  });

  it("dit comment chaque appareil est placé", () => {
    const names = new Map([["washer", "Lave-linge"]]);
    const text = (change: Partial<DeviceSettings>) => deviceText(settings("x", change), names, t, "fr");
    expect(text({})).toBe("Quand une tâche de Home Assistant ou une demande le prévoit");
    expect(text({ after: "washer" })).toBe("Toujours après Lave-linge");
    expect(text({ recurrence: { rule: "FREQ=DAILY" } })).toBe("Tous les jours");
    expect(text({ recurrence: { rule: "FREQ=WEEKLY;BYDAY=MO,TH" } })).toBe("Toutes les semaines, le lundi et jeudi");
    expect(
      text({
        behavior: "EnergyByDeadlineBehavior",
        energy: { energy_kwh: 5, earliest_hour: 0, deadline_hour: 7, max_kw: 2, steps: false, daily: true },
      }),
    ).toBe("5 kWh avant 7 h, tous les jours");
    expect(
      text({
        behavior: "RuntimeBehavior",
        runtime: { speeds: [], minimum_hours: { summer: 4, mid_season: 2, winter: 0 }, skip_days: {}, max_starts: 2 },
      }),
    ).toBe("4 h l'été, 2 h à la mi-saison et rien l'hiver");
    expect(text({ constraints: [{ kind: "forbidden", start_hour: 22, end_hour: 7, hard: true }] })).toBe(
      "Quand une tâche de Home Assistant ou une demande le prévoit · jamais entre 22 h et 7 h",
    );
  });
});

const HOME: HomeModel = {
  devices: [
    { key: "solar", kind: "SolarInstallation", name: "Panneaux", sensors: [], capacity_kwh: null },
    { key: "battery", kind: "Battery", name: "Batterie", sensors: [], capacity_kwh: 5.12 },
    { key: "washer", kind: "WashingMachine", name: "Lave-linge", sensors: [], capacity_kwh: null },
    { key: "fridge", kind: "OtherLoad", name: "Frigo", sensors: [], capacity_kwh: null },
  ],
};

const CONFIGURATION: Configuration = {
  version: 1,
  devices: [
    settings("solar", {
      behavior: "ProductionBehavior",
      panels: {
        arrays: [
          { kwp: 3, tilt: 30, azimuth: 180 },
          { kwp: 3, tilt: 30, azimuth: 90 },
        ],
        inverter_kw: null,
        efficiency: 0.9,
      },
    }),
    settings("battery", { behavior: "StorageBehavior" }),
    settings("washer", {}),
    settings("fridge", { behavior: "UncontrolledBehavior", planned: false }),
  ],
  tariff: BLANK_TARIFF,
  battery: {
    charge_max_w: null,
    discharge_max_w: null,
    floor_percent: 12,
    active_from_hour: 0,
    active_to_hour: 24,
    full_charge_every_days: 6,
  },
  objective: { preset: "cost", weights: null },
};

function renderHome(props: { anchor?: string; onAnchor?: () => void; onNavigate?: (target: string) => void } = {}) {
  return render(
    <I18nProvider>
      <HomeScreen page="main" onNavigate={props.onNavigate ?? vi.fn()} anchor={props.anchor} onAnchor={props.onAnchor} />
    </I18nProvider>,
  );
}

describe("Ma maison en onglets", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/home") return Response.json(HOME);
      if (url === "api/configuration") return Response.json(CONFIGURATION);
      return new Response(null, { status: 404 });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("résume l'essentiel en phrases et ouvre la feuille d'un réglage", async () => {
    renderHome();
    expect(screen.getByRole("tab", { name: "L'essentiel" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("button", { name: /Ma priorité\s*Payer le moins cher/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mon contrat\s*Heures creuses 22 h – 6 h/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Panneaux\s*2 champ\(s\), sud et est · 6 kWc/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Batterie\s*5,1 kWh, jamais sous 12 % · pleine au moins tous les 6 jours/ }),
    ).toBeInTheDocument();
    // Les appareils sont dans leur onglet.
    expect(screen.queryByRole("button", { name: /Lave-linge/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Batterie/ }));
    const sheet = screen.getByRole("dialog", { name: "Batterie" });
    expect(within(sheet).getByLabelText(/Ne jamais décharger en dessous de/)).toHaveValue(12);
    await userEvent.click(within(sheet).getByRole("button", { name: "Fermer" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("range les appareils placés, replie ceux suivis seulement, et garde l'onglet", async () => {
    const onNavigate = vi.fn();
    renderHome({ onNavigate });
    await userEvent.click(await screen.findByRole("tab", { name: "Appareils" }));
    expect(window.localStorage.getItem(TAB_KEY)).toBe("devices");
    expect(screen.getByRole("button", { name: /Lave-linge\s*Quand une tâche de Home Assistant ou une demande le prévoit/ })).toBeInTheDocument();
    const summary = screen.getByText("Frigo", { selector: "summary .ui-row-label" });
    const followed = summary.closest("details")!;
    expect(followed.open).toBe(false);
    expect(followed).toHaveTextContent("Mesurés, pas placés");

    await userEvent.click(summary);
    await userEvent.click(within(followed).getByRole("button", { name: "Frigo" }));
    expect(screen.getByRole("dialog", { name: "Frigo" })).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Fermer" }));

    await userEvent.click(screen.getByRole("button", { name: "Ajouter un appareil" }));
    expect(screen.getByRole("dialog", { name: "Ajouter un équipement absent du tableau Énergie" })).toBeInTheDocument();
  });

  it("ouvre la feuille demandée par un lien, dans son onglet", async () => {
    window.localStorage.setItem(TAB_KEY, "more");
    const onAnchor = vi.fn();
    renderHome({ anchor: "settings-washer", onAnchor });
    expect(await screen.findByRole("dialog", { name: "Lave-linge" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Appareils" })).toHaveAttribute("aria-selected", "true");
    expect(onAnchor).toHaveBeenCalled();
  });
});

describe("reveal", () => {
  it("déplie la section repliée qui contient l'ancre", () => {
    render(
      <details>
        <summary>Réglages détaillés</summary>
        <h3 id="battery">Batterie</h3>
      </details>,
    );
    const details = screen.getByText("Réglages détaillés").closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(reveal("battery")).toBe(true);
    expect(details.open).toBe(true);
    expect(reveal("missing")).toBe(false);
  });
});
