import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import CurvesScreen from "./CurvesScreen";
import { CurvesCustomizeButton } from "./PlanActions";
import { DAY_CARDS, type DashboardLayout, DEFAULT_LAYOUT } from "./layout";
import { TODAY, WEEK, WITHOUT_BATTERY } from "./testViews";
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
  // Comme dans App : le bouton « Personnaliser » est dans la barre de titre, hors de l'écran.
  render(
    <I18nProvider>
      <header>
        <CurvesCustomizeButton />
      </header>
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

  it("signale une mesure impossible écartée et mène à l'onglet Données de Ma maison", async () => {
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }), { ...TODAY, discarded_hours: [0] });
    renderScreen();

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Mesure impossible écartée à 0 h : sans doute une coupure d'un capteur.");
    const link = screen.getByRole("link", { name: "Voir les données" });
    expect(link).toHaveAttribute("href", "#/home");
    await userEvent.click(link);
    expect(window.localStorage.getItem("home.tab")).toBe("data");
  });

  it("Semaine : signale les mesures impossibles du jour qui ouvre la semaine", async () => {
    const user = userEvent.setup();
    mockApi(
      () => ({ yesterday: null, today: 1, tomorrow: null, week: 2 }),
      TODAY,
      DEFAULT_LAYOUT,
      { ...WEEK, discarded_hours: [9] },
    );
    renderScreen();

    await user.click(await screen.findByRole("tab", { name: "Semaine" }));
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Mesure impossible écartée à 9 h : sans doute une coupure d'un capteur.");
  });

  it("ne signale rien sans mesure écartée", async () => {
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    renderScreen();

    await screen.findByText("graphique 24 heures, relevé 14.5");
    expect(screen.queryByRole("note")).toBeNull();
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
    // Le détail d'un jour se déplie d'abord dans le tableau de la semaine.
    await user.click((await screen.findAllByRole("button", { expanded: false }))[0]);
    await user.click(screen.getByRole("button", { name: /Voir le détail/ }));
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

  it("montre « Personnaliser » dans la barre de titre une fois la vue ouverte", async () => {
    mockApi(() => ({ yesterday: null, today: 1, tomorrow: null, week: null }));
    renderScreen();

    const tabs = await screen.findByRole("tablist", { name: "Courbes" });
    const button = await screen.findByRole("button", { name: "Personnaliser" });
    expect(tabs).not.toContainElement(button);
    expect(button).toHaveTextContent(""); // icône seule : le nom reste au lecteur d'écran
    expect(button).toHaveAttribute("aria-pressed", "false");
  });

  it("Aujourd'hui : change le créneau d'un équipement pas encore lancé depuis la frise", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const day: DayView = {
      ...TODAY,
      timeline: {
        ...TODAY.timeline,
        rows: [
          ...TODAY.timeline.rows,
          {
            device: "Sèche-linge",
            kind: "cycle",
            planned: [{ start_hour: 16, end_hour: 17, energy_kwh: 1, action: null, mode: null }],
            actual: [],
          },
        ],
      },
      explanations: [
        {
          device: "Sèche-linge",
          text: "Placé à 16h.",
          explanation: {
            alternatives: [{ debut_min: 1140, ecart_cout_eur: -0.099, ecart_soutirage_kwh: -0.732 }],
            choisi: false,
          },
        },
      ],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "api/views/versions") return Response.json({ yesterday: 1, today: 1, tomorrow: 1, week: 1 });
      if (url.startsWith("api/views/today")) return Response.json(day);
      if (url.startsWith("api/views/tomorrow")) return Response.json({ ...day, kind: "tomorrow", cards: null });
      if (url === "api/settings/dashboard") return Response.json(DEFAULT_LAYOUT);
      if (url === "api/planning/choices" && init?.method === "POST") {
        return Response.json(JSON.parse(String(init.body)), { status: 201 });
      }
      if (url.startsWith("api/planning/choices/") && init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      if (url === "api/planning/run" && init?.method === "POST") return Response.json({});
      return new Response(null, { status: 404 });
    });
    const user = userEvent.setup();
    renderScreen();

    // Aujourd'hui : le bloc prévu pas encore lancé ouvre la feuille des autres départs.
    await user.click(await screen.findByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByRole("heading", { name: "Départ de Sèche-linge" })).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: /Choisir le départ de 19h00/ }));

    const posts = fetchMock.mock.calls.filter((call) => String(call[0]) === "api/planning/choices");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(String(posts[0][1]?.body))).toEqual({ device: "Sèche-linge", start_min: 1140 });
    expect(screen.queryByRole("dialog")).toBeNull();

    // Demain : le choix ne vaut que pour aujourd'hui, le bloc reste une info-bulle.
    await user.click(screen.getByRole("tab", { name: "Demain" }));
    await user.click(await screen.findByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    expect(screen.getByRole("status")).toHaveTextContent("Prévu 16h → 17h : Sèche-linge, 1,00 kWh");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
