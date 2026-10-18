import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import PlanScreen, { CURVES_KEY, POLL_MS } from "./PlanScreen";
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
      <PlanScreen />
    </I18nProvider>,
  );
}

describe("PlanScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // Les cartes de la phase 5 sont sous « Courbes détaillées » (lot 6b.4) : ouvertes ici.
    window.localStorage.setItem(CURVES_KEY, "open");
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

  it("passe d'une vue à l'autre et dit quand un plan manque", async () => {
    const user = userEvent.setup();
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: 2 }));
    renderScreen();

    await user.click(await screen.findByRole("tab", { name: "Semaine" }));
    expect(await screen.findByText("Semaine du samedi 17 octobre au lundi 19 octobre")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Hier" }));
    expect(await screen.findByText("Pas d'archive pour hier.")).toBeInTheDocument();
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

  it("montre la journée en agenda, courbes détaillées repliées par défaut", async () => {
    const user = userEvent.setup();
    window.localStorage.removeItem(CURVES_KEY);
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    renderScreen();

    expect(await screen.findByRole("list", { name: "Agenda de la journée" })).toBeInTheDocument();
    expect(screen.queryByText("graphique 24 heures, relevé 14.5")).toBeNull();
    await user.click(screen.getByText("Courbes détaillées"));
    expect(await screen.findByText("graphique 24 heures, relevé 14.5")).toBeInTheDocument();
    expect(window.localStorage.getItem(CURVES_KEY)).toBe("open");
  });

  it("rouvre la dernière vue ouverte dans ce navigateur", async () => {
    const user = userEvent.setup();
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: 2 }));
    renderScreen();
    await user.click(await screen.findByRole("tab", { name: "Semaine" }));
    expect(window.localStorage.getItem("plan.tab")).toBe("week");
  });

  it("recharge la vue quand un nouveau calcul arrive", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let version = 1;
    const fetchMock = mockApi(() => ({ yesterday: null, today: version, tomorrow: null, week: null }));
    renderScreen();
    await screen.findByText("graphique 24 heures, relevé 14.5");
    const views = () => fetchMock.mock.calls.filter(([url]) => String(url).startsWith("api/views/today")).length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50); // première version lue, vue rechargée une fois
    });
    const before = views();

    version = 2;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });

    expect(views()).toBe(before + 1);
  });
});
