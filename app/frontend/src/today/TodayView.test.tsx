// Écran Aujourd'hui (lot 6b.3) : le moment, la prochaine action et ses boutons, la batterie, le
// soleil ; sans mesures, la recommandation du jour.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { TODAY } from "../plan/testViews";
import type { DayView, NextAction, Now } from "../plan/types";
import TodayView, { LAUNCHED_KEY } from "./TodayView";

const NOW: Now = {
  since: "2026-10-17T10:00:00Z",
  until: "2026-10-17T10:15:00Z",
  production_w: 1800,
  consumption_w: 2200,
  battery_w: -200,
  grid_w: 200,
  soc_percent: 64,
  off_peak: false,
  sentence: "Le soleil couvre 82 % de la maison",
};

const ACTION: NextAction = {
  device: "Lave-linge",
  start_min: 780,
  end_min: 900,
  explanation: "Au plus fort du soleil.",
  reminder: false,
  can_remind: true,
};

function mockApi(view: DayView | null, features: object | null = null) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/home/features" && features) return Response.json(features);
    if (url.startsWith("api/views/today")) {
      return view === null ? new Response(null, { status: 404 }) : Response.json(view);
    }
    if (url === "api/reminders" && init?.method === "POST") {
      return Response.json({ device: "Lave-linge", day: "2026-10-17" }, { status: 201 });
    }
    return new Response(null, { status: 404 });
  });
}

function renderView() {
  return render(
    <I18nProvider>
      <TodayView />
    </I18nProvider>,
  );
}

describe("TodayView", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("résume le moment en une phrase et quatre flux", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: ACTION });
    renderView();
    const card = (await screen.findByRole("heading", { name: "Le soleil couvre 82 % de la maison" })).closest("section");
    const now = within(card as HTMLElement);
    expect(now.getByText("1,8 kW")).toBeInTheDocument();
    expect(now.getByText("2,2 kW")).toBeInTheDocument();
    expect(now.getByText("64 % · fournit 200 W")).toBeInTheDocument();
    expect(now.getByText("achat 200 W")).toBeInTheDocument();
  });

  it("affiche les puissances sous 1 kW en watts", async () => {
    mockApi({ ...TODAY, now: { ...NOW, production_w: 48, consumption_w: 0, battery_w: 288.4, grid_w: -999.6 }, next_action: ACTION });
    renderView();
    const card = (await screen.findByRole("heading", { name: "Le soleil couvre 82 % de la maison" })).closest("section");
    const now = within(card as HTMLElement);
    expect(now.getByText("48 W")).toBeInTheDocument();
    expect(now.getByText("0 W")).toBeInTheDocument();
    expect(now.getByText("64 % · charge 288 W")).toBeInTheDocument();
    expect(now.getByText(/1,0 kW/)).toBeInTheDocument();
  });

  it("montre la recommandation du jour sans mesures du moment", async () => {
    mockApi({ ...TODAY, now: { ...NOW, sentence: null }, recommendation: "Lancez le lave-linge à 13 h." });
    renderView();
    expect(await screen.findByRole("heading", { name: "Le plan du jour" })).toBeInTheDocument();
    expect(screen.getByText("Lancez le lave-linge à 13 h.")).toBeInTheDocument();
  });

  it("propose la prochaine action, la cache une fois lancée", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: ACTION });
    renderView();
    expect(await screen.findByRole("heading", { name: "Lancez Lave-linge" })).toBeInTheDocument();
    expect(screen.getByText(/Entre 13h00 et 15h00\. Au plus fort du soleil\./)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "C'est lancé" }));
    expect(screen.getByRole("heading", { name: "Rien à lancer d'ici ce soir" })).toBeInTheDocument();
    expect(window.localStorage.getItem(LAUNCHED_KEY)).toContain("Lave-linge");
  });

  it("pose un rappel, et n'en propose pas sans service de notification", async () => {
    const fetch = mockApi({ ...TODAY, now: NOW, next_action: ACTION });
    const { unmount } = renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Me le rappeler" }));
    expect(screen.getByRole("button", { name: "Rappel prévu" })).toBeDisabled();
    const post = fetch.mock.calls.find(([url, init]) => url === "api/reminders" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ device: "Lave-linge" });
    unmount();

    vi.restoreAllMocks();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    mockApi({ ...TODAY, now: NOW, next_action: { ...ACTION, can_remind: false } });
    renderView();
    await screen.findByRole("heading", { name: "Lancez Lave-linge" });
    expect(screen.queryByRole("button", { name: /rappel/i })).not.toBeInTheDocument();
  });

  it("donne la batterie et le soleil du jour, avec leur tendance au relevé", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: null });
    renderView();
    expect(await screen.findByRole("heading", { name: "64 % en ce moment" })).toBeInTheDocument();
    expect(screen.getByText("Au plus haut vers 16h00 : 98 %.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "10,0 kWh prévus aujourd'hui" })).toBeInTheDocument();
    expect(screen.getByText("14,0 kWh déjà produits.")).toBeInTheDocument();
    // Tendances de TODAY : SoC +25 %, production +8 %, en pilule en tête de chaque carte.
    expect(screen.getAllByTitle("Écart avec la prévision au relevé")).toHaveLength(2);
    expect(screen.getByText("▲ +25%")).toHaveClass("trend-pill");
    expect(screen.getByText("▲ +8%")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rien à lancer d'ici ce soir" })).toBeInTheDocument();
  });

  it("sans mesure au relevé : pas d'indicateur de tendance", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: null, cards: null });
    renderView();
    expect(await screen.findByRole("heading", { name: "64 % en ce moment" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "10,0 kWh prévus aujourd'hui" })).toBeInTheDocument();
    expect(screen.queryByText(/[▲▼●]/)).not.toBeInTheDocument();
  });

  it("sans solaire : pas de carte Soleil", async () => {
    mockApi({ ...TODAY, solar: false, now: NOW, next_action: null });
    renderView();
    expect(await screen.findByRole("heading", { name: "64 % en ce moment" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "10,0 kWh prévus aujourd'hui" })).not.toBeInTheDocument();
    expect(screen.queryByText("Soleil")).not.toBeInTheDocument();
  });

  it("sans appareil à placer : invite à en ajouter un", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: null }, { solar: true, battery: false, appliances: 0 });
    const onNavigate = vi.fn();
    render(
      <I18nProvider>
        <TodayView onNavigate={onNavigate} />
      </I18nProvider>,
    );
    expect(await screen.findByRole("heading", { name: "Aucun appareil à placer" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ajouter un appareil" }));
    expect(onNavigate).toHaveBeenCalledWith("devices#add-device");
  });

  it("dit qu'un plan calculé pendant la reprise de l'historique est provisoire", async () => {
    mockApi({ ...TODAY, now: NOW, history_pending: 3 });
    renderView();
    expect(await screen.findByRole("note")).toHaveTextContent("Plan provisoire");
    expect(screen.getByRole("note")).toHaveTextContent("3 compteur(s) restant(s)");
  });

  it("dit quand il n'y a pas encore de plan", async () => {
    mockApi(null);
    renderView();
    expect(await screen.findByText(/Pas encore de plan pour aujourd'hui/)).toBeInTheDocument();
  });
});
