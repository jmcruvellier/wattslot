import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import TemplateSection, { type TemplateSummary } from "./TemplateSection";

const TEMPLATES: TemplateSummary[] = [
  {
    key: "tempo",
    name: { fr: "Solaire, Tempo", en: "Solar, Tempo" },
    description: { fr: "Tarif Tempo.", en: "Tempo tariff." },
    tariff_kind: "DayColorTariff",
    devices: ["dryer"],
  },
  {
    key: "off_peak",
    name: { fr: "Solaire, heures creuses", en: "Solar, off-peak hours" },
    description: { fr: "Heures creuses.", en: "Off-peak hours." },
    tariff_kind: "TimeOfUseTariff",
    devices: ["dryer"],
  },
];

const HOME = {
  devices: [{ key: "dryer", kind: "Dryer", name: "Sèche-linge", sensors: [] }],
};

type Calls = { url: string; body: unknown }[];

function mockApi(): Calls {
  const calls: Calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url, body });
    if (url === "api/templates") return Response.json(TEMPLATES);
    if (url === "api/home") return Response.json(HOME);
    if (url === "api/configuration") return Response.json({ version: 1, devices: [], tariff: null });
    if (url.endsWith("/preview")) {
      const missing = url.includes("tempo") && !body?.color_entity;
      return Response.json({
        template: "x",
        changes: [
          {
            part: "device",
            device: "dryer",
            before: { behavior: "UncontrolledBehavior" },
            after: { behavior: "CycleBehavior" },
          },
          { part: "tariff", device: null, before: null, after: {} },
        ],
        issues: missing ? [{ code: "tariff_without_color_entity", device: null, params: {} }] : [],
      });
    }
    if (url.endsWith("/apply")) return Response.json({ version: 1, devices: [] });
    return new Response(null, { status: 404 });
  });
  return calls;
}

function renderSection(onApplied = vi.fn()) {
  render(
    <I18nProvider>
      <TemplateSection version={0} onApplied={onApplied} />
    </I18nProvider>,
  );
  return onApplied;
}

describe("TemplateSection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("montre ce qui changerait puis applique le modèle", async () => {
    const user = userEvent.setup();
    const calls = mockApi();
    const onApplied = renderSection();

    expect(await screen.findAllByText("Réglerait : Sèche-linge.")).toHaveLength(2);
    await user.click(screen.getByLabelText("Solaire, heures creuses"));
    await user.click(screen.getByRole("button", { name: "Voir ce qui changerait" }));

    expect(
      await screen.findByText("Sèche-linge : Consommation seulement suivie → Cycle à démarrer"),
    ).toBeTruthy();
    expect(screen.getByText(/Tarif de l'électricité remplacé/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Appliquer le modèle" }));

    expect(await screen.findByText(/Modèle appliqué/)).toBeTruthy();
    expect(onApplied).toHaveBeenCalledOnce();
    expect(calls.some((call) => call.url === "api/templates/off_peak/apply")).toBe(true);
  });

  it("demande l'entité de la couleur du jour pour Tempo", async () => {
    const user = userEvent.setup();
    const calls = mockApi();
    renderSection();

    await user.click(await screen.findByLabelText("Solaire, Tempo"));
    await user.click(screen.getByRole("button", { name: "Voir ce qui changerait" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Appliquer le modèle" }) as HTMLButtonElement).disabled).toBe(true);

    await user.type(screen.getByLabelText("Capteur de la couleur du jour"), "sensor.tempo_today");
    await user.click(screen.getByRole("button", { name: "Voir ce qui changerait" }));
    await user.click(await screen.findByRole("button", { name: "Appliquer le modèle" }));

    const applied = calls.find((call) => call.url === "api/templates/tempo/apply");
    expect(applied?.body).toEqual({ color_entity: "sensor.tempo_today" });
  });

  it("attend que la maison soit enregistrée", async () => {
    mockApi();
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url === "api/templates") return Response.json(TEMPLATES);
      if (url === "api/home") return Response.json({ devices: [] });
      return Response.json({ version: 1, devices: [], tariff: null });
    });
    renderSection();

    expect(await screen.findByText(/Enregistrez d'abord votre maison/)).toBeTruthy();
  });
});
