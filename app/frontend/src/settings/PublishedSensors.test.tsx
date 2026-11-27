import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import PublishedSensors, { type PublishedSensorsState } from "./PublishedSensors";

const OFF: PublishedSensorsState = {
  consumption_forecast: false,
  entities: [
    "sensor.wattslot_home_consumption_forecast_remaining_today",
    "sensor.wattslot_home_consumption_forecast_today",
    "sensor.wattslot_home_consumption_forecast_tomorrow",
  ],
  available: true,
  published_at: null,
  error: null,
};

type Calls = { url: string; method: string; body: unknown }[];

function mockApi(initial: PublishedSensorsState | null, saved: Partial<PublishedSensorsState> | null = {}): Calls {
  const calls: Calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as Partial<PublishedSensorsState>) : null;
    calls.push({ url: String(input), method, body });
    if (initial === null) return new Response(null, { status: 404 });
    if (method === "PUT") {
      return saved === null ? new Response(null, { status: 500 }) : Response.json({ ...initial, ...body, ...saved });
    }
    return Response.json(initial);
  });
  return calls;
}

function renderSection() {
  return render(
    <I18nProvider>
      <PublishedSensors />
    </I18nProvider>,
  );
}

describe("PublishedSensors", () => {
  beforeEach(() => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("est désactivé par défaut, sans la liste des capteurs", async () => {
    mockApi(OFF);
    renderSection();
    const toggle = await screen.findByRole("switch", { name: "Publier la prévision de consommation de la maison" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/expérimental/)).toBeInTheDocument();
    expect(screen.queryByText(OFF.entities[0])).not.toBeInTheDocument();
  });

  it("enregistre tout de suite et montre les capteurs écrits", async () => {
    const calls = mockApi(OFF, { published_at: "2026-11-27T10:15:05Z" });
    renderSection();
    await userEvent.click(await screen.findByRole("switch"));
    expect(calls.at(-1)).toEqual({ url: "api/settings/sensors", method: "PUT", body: { consumption_forecast: true } });
    expect(await screen.findByText(OFF.entities[0])).toBeInTheDocument();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("status")).toHaveTextContent(/^Capteurs écrits à \d{2}:15\.$/);
  });

  it("dit que le compte doit être administrateur quand Home Assistant refuse", async () => {
    mockApi({ ...OFF, consumption_forecast: true, error: "refused" });
    renderSection();
    expect(await screen.findByRole("alert")).toHaveTextContent(/doit être administrateur/);
  });

  it("garde le réglage et le dit quand l'enregistrement échoue", async () => {
    mockApi(OFF, null);
    renderSection();
    await userEvent.click(await screen.findByRole("switch"));
    expect(await screen.findByRole("alert")).toHaveTextContent("L'enregistrement a échoué.");
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("n'affiche rien si le serveur ne répond pas", async () => {
    const calls = mockApi(null);
    const { container } = renderSection();
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    expect(container).toBeEmptyDOMElement();
  });
});
