// Liste des Réglages (lot 6b.6) : un résumé par ligne, chaque ligne vers sa sous-page.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import SettingsHome from "./SettingsHome";

const OFF = { enabled: false, service: null, quiet_hours: null };

function mockApi() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "api/settings/notifications") {
      return Response.json({
        service: "notify.mobile_app_phone",
        language: "fr",
        recommendation: { ...OFF, enabled: true, cadence: "every_run", daily_at: "07:00" },
        device_now: { ...OFF, enabled: true },
        plan_gap: OFF,
        battery_full: OFF,
        forecast_drop: OFF,
      });
    }
    if (url === "api/settings/choices") {
      return Response.json({
        connected: true,
        todo_lists: [],
        notify_services: [{ id: "notify.mobile_app_phone", name: "Téléphone" }],
        forecast_entities: [],
      });
    }
    if (url === "api/settings/planning") return Response.json({ scheduler_enabled: true, run_minute: 59 });
    if (url === "api/health") {
      return Response.json({
        version: "1",
        mode: "standalone",
        connections: { home_assistant: { state: "connected", version: null, error: null } },
      });
    }
    if (url === "api/diagnostic/problems") return Response.json([]);
    return new Response(null, { status: 404 });
  });
}

describe("SettingsHome", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("résume chaque réglage et mène à sa sous-page", async () => {
    mockApi();
    render(
      <I18nProvider>
        <SettingsHome />
      </I18nProvider>,
    );
    const link = async (name: RegExp) => screen.findByRole("link", { name });
    expect(await link(/Notifications\s*2 active\(s\), sur Téléphone/)).toHaveAttribute("href", "#/settings/notifications");
    // Serveur MCP absent du faux serveur : la ligne de l'assistant dit qu'il ne répond pas.
    expect(await link(/Assistant vocal\s*Le serveur de l'assistant ne répond pas/)).toHaveAttribute(
      "href",
      "#/settings/voice",
    );
    // « Mes demandes » est dans Planning, plus dans les Réglages.
    expect(screen.queryByRole("link", { name: /Mes demandes/ })).not.toBeInTheDocument();
    expect(await link(/Langue et affichage\s*Français · Automatique/)).toHaveAttribute("href", "#/settings/display");
    expect(await link(/État de l'application\s*Tout fonctionne/)).toHaveAttribute("href", "#/settings/status");
    expect(await link(/Calcul automatique\s*Toutes les heures, à la minute 59/)).toHaveAttribute(
      "href",
      "#/settings/calculation",
    );
    expect(await link(/Sauvegarder ou partager/)).toHaveAttribute("href", "#/home/backup");
    expect(await link(/Connexion à Home Assistant\s*Connecté/)).toHaveAttribute("href", "#/settings/connection");
  });
});
