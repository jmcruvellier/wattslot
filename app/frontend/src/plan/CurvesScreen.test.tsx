import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import CurvesScreen from "./CurvesScreen";
import { DAY_CARDS, type DashboardLayout, DEFAULT_LAYOUT } from "./layout";
import { TODAY, WEEK, WITHOUT_BATTERY } from "./testViews";
import type { DayView, HourPoint } from "./types";

// Recharts mesure son conteneur, ce que jsdom ne sait pas faire : graphique remplacé.
vi.mock("./Charts", () => {
  const chart =
    (name: string) =>
    ({ hours, readingHour }: { hours: HourPoint[]; readingHour: number | null }) => (
      <p>
        {name} {hours.length} heures, relevé {readingHour === null ? "aucun" : readingHour}
      </p>
    );
  return { EnergyChart: chart("graphique"), SocChart: chart("soc"), GridChart: chart("réseau"), WeekChart: () => null };
});

function mockApi(
  versions: () => Record<string, number | null>,
  today: DayView = TODAY,
  layout: DashboardLayout = DEFAULT_LAYOUT,
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/views/versions") return Response.json(versions());
    if (url.startsWith("api/views/today")) return Response.json(today);
    if (url.startsWith("api/views/week")) return Response.json(WEEK);
    if (url === "api/settings/dashboard") {
      return Response.json(init?.method === "PUT" ? { ...JSON.parse(String(init.body)), default: false } : layout);
    }
    return Response.json({ detail: "no_plan" }, { status: 404 });
  });
}

function renderScreen() {
  render(
    <I18nProvider>
      <CurvesScreen />
    </I18nProvider>,
  );
}

describe("CurvesScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("ouvre Aujourd'hui avec la carte des énergies, sans lien vers l'ancien dashboard", async () => {
    const fetchMock = mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    renderScreen();

    expect(await screen.findByText("graphique 24 heures, relevé 14.5")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Production et consommation" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Aujourd'hui" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("link", { name: "Ancien dashboard" })).toBeNull(); // supprimé (lot 7.1)
    expect(fetchMock).toHaveBeenCalledWith("api/views/today?lang=fr", expect.anything());
  });

  it("montre la frise et les graphiques de la batterie et du réseau", async () => {
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    renderScreen();

    expect(await screen.findByText("soc 24 heures, relevé 14.5")).toBeInTheDocument();
    expect(await screen.findByText("réseau 24 heures, relevé 14.5")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Planning des équipements" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Batterie (SoC)" })).toBeInTheDocument();
  });

  it("sans batterie : pas de graphique du SoC", async () => {
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }), WITHOUT_BATTERY);
    renderScreen();

    expect(await screen.findByText("réseau 24 heures, relevé 14.5")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Batterie (SoC)" })).toBeNull();
  });

  it("Semaine : « Voir le détail » ouvre l'onglet du jour", async () => {
    const user = userEvent.setup();
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: 2 }));
    renderScreen();

    await user.click(await screen.findByRole("tab", { name: "Semaine" }));
    await user.click((await screen.findAllByRole("button", { name: /Voir le détail/ }))[0]);
    expect(screen.getByRole("tab", { name: "Aujourd'hui" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("graphique 24 heures, relevé 14.5")).toBeInTheDocument();
  });

  it("applique la disposition de l'installation et enregistre une carte masquée", async () => {
    const user = userEvent.setup();
    const saved = { ...DEFAULT_LAYOUT, default: false, today: { order: [...DAY_CARDS], hidden: ["energy" as const] } };
    const fetchMock = mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }), TODAY, saved);
    renderScreen();

    expect(await screen.findByText("réseau 24 heures, relevé 14.5")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Production et consommation" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Personnaliser" }));
    await user.click(screen.getByRole("button", { name: "Masquer « Réseau »" }));
    expect(screen.queryByText("réseau 24 heures, relevé 14.5")).toBeNull();
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(put?.[0]).toBe("api/settings/dashboard");
    expect(JSON.parse(String(put?.[1]?.body)).today.hidden).toEqual(["energy", "grid"]);
    expect(JSON.parse(String(put?.[1]?.body))).not.toHaveProperty("default");
  });

  it("laisse « Pourquoi ce plan » et les indicateurs à Planning", async () => {
    const user = userEvent.setup();
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    renderScreen();

    expect(await screen.findByText("graphique 24 heures, relevé 14.5")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Pourquoi ce plan" })).toBeNull();
    expect(screen.queryByRole("article", { name: "Indicateurs du plan" })).toBeNull();
    // Le choix des indicateurs reste dans « Personnaliser », mais plus leurs cartes.
    await user.click(screen.getByRole("button", { name: "Personnaliser" }));
    expect(screen.getByRole("group", { name: "Indicateurs du plan" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Masquer « Indicateurs du plan »" })).toBeNull();
  });
});
