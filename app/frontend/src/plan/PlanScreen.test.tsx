import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import PlanScreen, { POLL_MS } from "./PlanScreen";
import { type DashboardLayout, DEFAULT_LAYOUT } from "./layout";
import { TODAY, WEEK, WITHOUT_INSIGHTS } from "./testViews";
import type { DayView, HourPoint, WeekView } from "./types";

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
  week: WeekView = WEEK,
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/views/versions") return Response.json(versions());
    if (url.startsWith("api/views/today")) return Response.json(today);
    if (url.startsWith("api/views/week")) return Response.json(week);
    if (url === "api/settings/dashboard") {
      return Response.json(init?.method === "PUT" ? { ...JSON.parse(String(init.body)), default: false } : layout);
    }
    return Response.json({ detail: "no_plan" }, { status: 404 });
  });
}

function renderScreen() {
  return render(
    <I18nProvider>
      <PlanScreen />
    </I18nProvider>,
  );
}

describe("PlanScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("montre la journée en agenda, puis « Pourquoi ce plan » et les indicateurs côte à côte, sans courbes", async () => {
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    const { container } = renderScreen();

    expect(await screen.findByRole("list", { name: "Agenda de la journée" })).toBeInTheDocument();
    const insights = container.querySelector(".plan-insights");
    const why = screen.getByRole("article", { name: "Pourquoi ce plan" });
    const indicators = screen.getByRole("article", { name: "Indicateurs du plan" });
    expect(why.parentElement).toBe(insights);
    expect(indicators.parentElement).toBe(insights);
    expect(why.compareDocumentPosition(indicators)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    // Un seul « Pourquoi ce plan », ouvert ; plus de courbes ni de « Personnaliser » ici.
    expect(screen.getAllByText("Pourquoi ce plan")).toHaveLength(1);
    expect(screen.getByText("Lave-linge")).toBeVisible();
    expect(screen.queryByText(/graphique/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Personnaliser" })).toBeNull();
  });

  it("applique l'indicateur mis en avant choisi dans « Personnaliser »", async () => {
    const saved: DashboardLayout = { ...DEFAULT_LAYOUT, default: false, indicators: { highlight: "cost_eur", hidden: [] } };
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }), TODAY, saved);
    const { container } = renderScreen();

    await waitFor(() => expect(container.querySelector(".indicator-main dt")).toHaveTextContent("Coût"));
  });

  it("sans explication ni indicateur : rien sous l'agenda", async () => {
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }), WITHOUT_INSIGHTS);
    const { container } = renderScreen();

    expect(await screen.findByRole("list", { name: "Agenda de la journée" })).toBeInTheDocument();
    expect(container.querySelector(".plan-insights")?.children).toHaveLength(0);
  });

  it("montre « Mes demandes » sous le plan", async () => {
    const plan = mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    const views = plan.getMockImplementation()!;
    plan.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "api/requests/devices") return Response.json([{ key: "washer", name: "Lave-linge" }]);
      if (url === "api/requests") return Response.json([]);
      return views(input, init);
    });
    renderScreen();

    expect(await screen.findByRole("heading", { name: "Mes demandes" })).toBeInTheDocument();
  });

  it("signale une mesure impossible écartée, sur le jour ouvert comme sur la semaine", async () => {
    const user = userEvent.setup();
    mockApi(
      () => ({ yesterday: null, today: 1, tomorrow: null, week: 2 }),
      { ...TODAY, discarded_hours: [9] },
      DEFAULT_LAYOUT,
      { ...WEEK, discarded_hours: [9] },
    );
    renderScreen();

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Mesure impossible écartée à 9 h : sans doute une coupure d'un capteur.");
    await user.click(screen.getByRole("link", { name: "Voir les données" }));
    expect(window.localStorage.getItem("home.tab")).toBe("data");

    await user.click(screen.getByRole("tab", { name: "Semaine" }));
    expect(await screen.findByRole("note")).toHaveTextContent("Mesure impossible écartée à 9 h");
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
    await screen.findByRole("list", { name: "Agenda de la journée" });
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
