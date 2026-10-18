// Accessibilité (lot 6b.7) : axe-core sur chaque section et les sous-pages principales, avec des
// données d'exemple. La règle des contrastes est coupée : jsdom ne calcule pas le rendu ; les
// contrastes de chaque thème sont vérifiés par theme/themes.test.ts.

import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { I18nProvider } from "./i18n/I18nProvider";
import { TODAY, WEEK } from "./plan/testViews";

const OFF = { enabled: false, service: null, quiet_hours: null };

const RESPONSES: Record<string, unknown> = {
  "api/health": {
    version: "1",
    mode: "standalone",
    connections: { home_assistant: { state: "connected", version: "2026.10.1", error: null } },
  },
  "api/setup": { ready: true, steps: [{ key: "connection", state: "done", required: true, reason: null, params: {}, target: null }] },
  "api/diagnostic/problems": [],
  "api/diagnostic": null,
  "api/views/versions": { yesterday: null, today: 1, tomorrow: null, week: 1 },
  "api/settings/dashboard": null,
  "api/settings/planning": {
    objective: "cost",
    todo_entity: null,
    forecast_entities: [],
    scheduler_enabled: true,
    run_minute: 59,
    notify_service: null,
    notify_language: "fr",
  },
  "api/settings/notifications": {
    service: null,
    language: "fr",
    recommendation: { ...OFF, cadence: "every_run", daily_at: "07:00" },
    device_now: OFF,
    plan_gap: OFF,
    battery_full: OFF,
    forecast_drop: OFF,
  },
  "api/settings/choices": { connected: true, todo_lists: [], notify_services: [], forecast_entities: [] },
  "api/planning/status": { enabled: true, next_run_at: null },
  "api/requests": [],
  "api/requests/devices": [{ key: "washer", name: "Lave-linge" }],
  "api/home": { devices: [{ key: "washer", kind: "WashingMachine", name: "Lave-linge", sensors: [], capacity_kwh: null }] },
  "api/configuration": {
    version: 1,
    devices: [{ key: "washer", behavior: "CycleBehavior", automation: "RecommendAutomation", planned: true, default: false, constraints: [] }],
    tariff: null,
    battery: null,
    objective: null,
  },
  "api/assistant/connection": { mode: "standalone", mcp_url: null },
};

function mockApi() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input).split("?")[0];
    if (url === "api/views/today") return Response.json({ ...TODAY, now: null, next_action: null });
    if (url === "api/views/week") return Response.json(WEEK);
    if (url.startsWith("api/assistant/prompt")) return Response.json({ language: "fr", prompt: "Prompt" });
    const found = RESPONSES[url];
    return found === undefined || found === null ? new Response(null, { status: 404 }) : Response.json(found);
  });
}

async function violations(): Promise<string[]> {
  const results = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
    resultTypes: ["violations"],
  });
  return results.violations.map(
    (violation) => `${violation.id} : ${violation.nodes.map((node) => node.target.join(" ")).join(", ")}`,
  );
}

// Section, et un texte qui dit que l'écran est chargé.
const PAGES: [string, string | RegExp][] = [
  ["#/today", "En ce moment"],
  ["#/planning", "Courbes détaillées"],
  ["#/home", "Ma priorité"],
  ["#/assistant", "Exemples de questions"],
  ["#/settings", "Notifications"],
  ["#/settings/notifications", "Appareil commun"],
  ["#/settings/display", "Thème"],
  ["#/settings/calculation", "Calcul automatique"],
];

describe("accessibilité", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    mockApi();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = "";
  });

  it.each(PAGES)("%s : aucune violation relevée par axe-core", async (hash, loaded) => {
    window.location.hash = hash;
    render(
      <I18nProvider>
        <App />
      </I18nProvider>,
    );
    await screen.findAllByText(loaded);
    expect(await violations()).toEqual([]);
  });
});
