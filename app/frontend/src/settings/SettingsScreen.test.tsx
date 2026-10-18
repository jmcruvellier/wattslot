import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import type { NotificationSettings } from "./NotificationSettings";
import SettingsScreen, { type PlanningSettings, type SettingsChoices, type SettingsPage } from "./SettingsScreen";

const SETTINGS: PlanningSettings = {
  objective: "cost",
  todo_entity: null,
  forecast_entities: [],
  scheduler_enabled: true,
  run_minute: 59,
  notify_service: null,
  notify_language: "fr",
};

const OFF = { enabled: false, service: null, quiet_hours: null };
const NOTIFICATIONS: NotificationSettings = {
  service: null,
  language: "fr",
  recommendation: { ...OFF, cadence: "every_run", daily_at: "07:00:00" },
  device_now: OFF,
  plan_gap: OFF,
  battery_full: OFF,
  forecast_drop: OFF,
};

const CHOICES: SettingsChoices = {
  connected: true,
  todo_lists: [{ id: "todo.courses", name: "Courses" }],
  notify_services: [{ id: "notify.mobile_app_phone", name: null }],
  forecast_entities: [{ id: "sensor.helios_forecast", name: "Prévision" }],
};

type Calls = { url: string; method: string; body: unknown }[];

function mockApi(notify: Response | null = null): Calls {
  const calls: Calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url === "api/settings/planning" && method === "PUT") return Response.json(JSON.parse(String(init?.body)));
    if (url === "api/settings/planning") return Response.json(SETTINGS);
    if (url === "api/settings/choices") return Response.json(CHOICES);
    if (url === "api/planning/status") return Response.json({ enabled: true, next_run_at: null });
    if (url === "api/settings/notifications" && method === "PUT") return Response.json(JSON.parse(String(init?.body)));
    if (url === "api/settings/notifications") return Response.json(NOTIFICATIONS);
    if (url.startsWith("api/notifications/")) return notify ?? Response.json({ detail: "no_plan" }, { status: 409 });
    return new Response(null, { status: 404 });
  });
  return calls;
}

// Chaque sous-page des Réglages (lot 6b.6) ; les notifications par défaut.
function renderScreen(page: SettingsPage = "notifications") {
  render(
    <I18nProvider>
      <SettingsScreen page={page} />
    </I18nProvider>,
  );
}

describe("SettingsScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calcul automatique : propose les choix de HA et n'enregistre que ses réglages", async () => {
    const user = userEvent.setup();
    const calls = mockApi();
    renderScreen("calculation");

    await user.selectOptions(await screen.findByLabelText("Liste de tâches"), "todo.courses");
    await user.click(screen.getByLabelText("Prévision (sensor.helios_forecast)"));
    await user.click(screen.getByLabelText("Recalculer le plan chaque heure"));
    expect(screen.queryByLabelText("Appareil commun")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Réglages enregistrés.")).toBeTruthy();
    const planning = calls.find((call) => call.method === "PUT" && call.url === "api/settings/planning");
    expect(planning?.body).toEqual({
      ...SETTINGS,
      todo_entity: "todo.courses",
      forecast_entities: ["sensor.helios_forecast"],
      scheduler_enabled: false,
    });
    expect(calls.some((call) => call.method === "PUT" && call.url === "api/settings/notifications")).toBe(false);
  });

  it("notifications : n'enregistre que leurs réglages", async () => {
    const user = userEvent.setup();
    const calls = mockApi();
    renderScreen("notifications");

    await user.selectOptions(await screen.findByLabelText("Appareil commun"), "notify.mobile_app_phone");
    expect(screen.queryByLabelText("Liste de tâches")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Réglages enregistrés.")).toBeTruthy();
    const notifications = calls.find((call) => call.method === "PUT" && call.url === "api/settings/notifications");
    expect((notifications?.body as NotificationSettings).service).toBe("notify.mobile_app_phone");
    expect(calls.some((call) => call.method === "PUT" && call.url === "api/settings/planning")).toBe(false);
  });

  it("règle chaque notification : activation, rythme, appareil, heures de silence", async () => {
    const user = userEvent.setup();
    const calls = mockApi();
    renderScreen();

    const recommendation = await screen.findByRole("group", { name: "Recommandation du jour" });
    await user.click(within(recommendation).getByLabelText("Recommandation du jour"));
    await user.selectOptions(within(recommendation).getByLabelText("Rythme"), "seulement quand le plan change");
    const gap = screen.getByRole("group", { name: "Écart au plan" });
    await user.click(within(gap).getByLabelText("Écart au plan"));
    await user.selectOptions(within(gap).getByLabelText("Appareil"), "notify.mobile_app_phone");
    await user.click(within(gap).getByLabelText("Heures de silence"));
    expect((within(gap).getByLabelText("de") as HTMLInputElement).value).toBe("22:00");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Réglages enregistrés.")).toBeTruthy();
    const put = calls.find((call) => call.method === "PUT" && call.url === "api/settings/notifications");
    const body = put?.body as NotificationSettings;
    expect(body.recommendation).toMatchObject({ enabled: true, cadence: "when_changed" });
    expect(body.plan_gap).toEqual({
      enabled: true,
      service: "notify.mobile_app_phone",
      quiet_hours: { start: "22:00", end: "07:00" },
    });
    expect(body.device_now.enabled).toBe(false); // rien d'activé sans le demander
  });

  it("une fois par jour : l'heure se règle", async () => {
    const user = userEvent.setup();
    mockApi();
    renderScreen();

    const recommendation = await screen.findByRole("group", { name: "Recommandation du jour" });
    expect(within(recommendation).queryByLabelText("à partir de")).toBeNull();
    await user.selectOptions(within(recommendation).getByLabelText("Rythme"), "une fois par jour");
    expect((within(recommendation).getByLabelText("à partir de") as HTMLInputElement).value).toBe("07:00");
  });

  it("accepte un service saisi à la main et dit pourquoi l'essai échoue", async () => {
    const user = userEvent.setup();
    const calls = mockApi();
    renderScreen();

    const test = await screen.findByRole("button", { name: "Envoyer un essai : Recommandation du jour" });
    expect((test as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByLabelText("Autre service de notification :"), "notify.tablette");
    await user.click(screen.getByRole("button", { name: "Utiliser" }));
    expect((screen.getByLabelText("Appareil commun") as HTMLSelectElement).value).toBe("notify.tablette");

    await user.click(test);

    expect(await screen.findByText(/Pas encore de plan du jour/)).toBeTruthy();
    const put = calls.find((call) => call.method === "PUT" && call.url === "api/settings/notifications");
    expect((put?.body as NotificationSettings).service).toBe("notify.tablette");
    expect(calls.some((call) => call.url === "api/notifications/recommendation/test")).toBe(true);
  });

  it("montre le message envoyé en essai, pour chaque notification", async () => {
    const user = userEvent.setup();
    const calls = mockApi(Response.json({ service: "notify.mobile_app_phone", message: "[Essai] Lancez Lave-linge maintenant." }));
    renderScreen();

    await user.selectOptions(await screen.findByLabelText("Appareil commun"), "notify.mobile_app_phone");
    await user.click(screen.getByRole("button", { name: "Envoyer un essai : « Lancez X maintenant »" }));

    expect(await screen.findByText("Essai envoyé : « [Essai] Lancez Lave-linge maintenant. »")).toBeTruthy();
    expect(calls.some((call) => call.url === "api/notifications/device_now/test")).toBe(true);
  });
});
