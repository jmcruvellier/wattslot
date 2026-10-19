import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { WEEK, WEEK_WITHOUT_BATTERY } from "./testViews";
import type { WeekView } from "./types";
import PlanActions from "./PlanActions";
import WeekScreen, { WeekDetails } from "./WeekScreen";
import { DEFAULT_LAYOUT, type ViewLayout } from "./layout";

// Recharts mesure son conteneur, ce que jsdom ne sait pas faire : graphique remplacé.
vi.mock("./Charts", () => ({
  WeekChart: ({ points, series, nowIndex }: { points: unknown[]; series: string; nowIndex: number | null }) => (
    <p>
      {series} {points.length} heures, relevé {nowIndex ?? "aucun"}
    </p>
  ),
}));

function renderWeek(view: WeekView, onOpen = vi.fn(), onChanged = vi.fn(), layout: ViewLayout = DEFAULT_LAYOUT.week) {
  render(
    <I18nProvider>
      <PlanActions kind="week" onChanged={onChanged} />
      <WeekScreen view={view} onOpen={onOpen} />
      <WeekDetails view={view} onOpen={onOpen} layout={layout} />
    </I18nProvider>,
  );
  return { onOpen, onChanged };
}

describe("vue Semaine", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("en-tête, avertissements de l'horizon et une carte par jour", () => {
    renderWeek(WEEK);

    expect(screen.getByText("Semaine du samedi 17 octobre au lundi 19 octobre")).toBeInTheDocument();
    expect(screen.getByText(/Horizon calculé à 13:59 \(à la main\) · calcul en 4,2 s/)).toBeInTheDocument();
    expect(screen.getByText(/Prévision manquante pour le 23 octobre/)).toBeInTheDocument();
    expect(screen.getByText(/ne sont placées que sur demain/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Semaine" })).getAllByRole("article")).toHaveLength(3);

    const today = screen.getByRole("article", { name: "samedi 17" });
    expect(within(today).getByText("Aujourd'hui")).toBeInTheDocument();
    expect(within(today).getByText(/ensoleillée/)).toBeInTheDocument();
    expect(within(today).getByText("12,3 kWh")).toBeInTheDocument();
    expect(within(today).getByText("40 → 55 %")).toBeInTheDocument();
    expect(within(today).getByText("98 %")).toBeInTheDocument();
    expect(within(today).getByText("0,25 kWh")).toBeInTheDocument();
    expect(within(today).getByText("Lave-linge")).toBeInTheDocument();
    expect(within(today).getByText("10h05–11h30")).toBeInTheDocument();

    const tomorrow = screen.getByRole("article", { name: "dimanche 18" });
    expect(within(tomorrow).getByText("Aucun équipement prévu")).toBeInTheDocument();
    expect(within(tomorrow).getByText(/Sèche-linge reporté/)).toBeInTheDocument();

    const later = screen.getByRole("article", { name: "lundi 19" });
    expect(within(later).queryByRole("button", { name: /Voir le détail/ })).toBeNull();
  });

  it("la semaine en agenda : une ligne par jour", async () => {
    const user = userEvent.setup();
    const { onOpen } = renderWeek(WEEK);
    const rows = within(screen.getByRole("list", { name: "Agenda de la semaine" })).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("samedi 17Aujourd'hui");
    expect(rows[0]).toHaveTextContent("ensoleillée · 12,3 kWh");
    expect(rows[0]).toHaveTextContent("Batterie : 40 %, jusqu'à 98 %, 55 % le soir");
    expect(rows[0]).toHaveTextContent("Lave-linge 10h05");
    expect(rows[1]).toHaveTextContent("Aucun équipement prévu");
    await user.click(within(rows[1]).getByRole("button", { name: /Ouvrir Demain/ }));
    expect(onOpen).toHaveBeenCalledWith("tomorrow");
    expect(within(rows[2]).queryByRole("button")).toBeNull();
  });

  it("« Voir le détail » ouvre la vue du jour", async () => {
    const user = userEvent.setup();
    const { onOpen } = renderWeek(WEEK);
    await user.click(within(screen.getByRole("article", { name: "dimanche 18" })).getByRole("button", { name: /Voir le détail/ }));
    expect(onOpen).toHaveBeenCalledWith("tomorrow");
  });

  it("« Calculer » lance un calcul puis recharge la vue", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({}));
    const { onChanged } = renderWeek(WEEK);
    await user.click(screen.getByRole("button", { name: "Calculer" }));
    expect(fetchMock).toHaveBeenCalledWith("api/planning/run", { method: "POST" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("graphiques de la semaine : production, consommation et SoC", async () => {
    renderWeek(WEEK);
    expect(await screen.findByText("soc 72 heures, relevé 13.5")).toBeInTheDocument();
    expect(screen.getByText("production 72 heures, relevé 13.5")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Consommation prévue" })).toHaveTextContent("Heures creuses");
  });

  it("sans batterie : ni lignes SoC ni graphique du SoC", async () => {
    renderWeek(WEEK_WITHOUT_BATTERY);
    expect(await screen.findByText("consumption 72 heures, relevé 13.5")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Batterie (SoC prévu)" })).toBeNull();
    const today = screen.getByRole("article", { name: "samedi 17" });
    expect(within(today).queryByText("SoC")).toBeNull();
    expect(within(today).getByText("Achat")).toBeInTheDocument();
  });

  it("cartes des jours avant les graphiques, production masquée", async () => {
    renderWeek(WEEK, vi.fn(), vi.fn(), { order: ["days", "soc", "consumption", "production"], hidden: ["production"] });
    expect(await screen.findByText("soc 72 heures, relevé 13.5")).toBeInTheDocument();
    expect(screen.queryByText(/^production 72/)).toBeNull();
    const region = screen.getByRole("region", { name: "Semaine" });
    const chart = screen.getByRole("article", { name: "Batterie (SoC prévu)" });
    expect(region.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("affiche les jours que le calcul n'a pas atteints, sans données", () => {
    renderWeek({ ...WEEK, missing_days: ["2026-10-20", "2026-10-21"] });

    const agenda = screen.getByRole("list", { name: "Agenda de la semaine" });
    const rows = within(agenda).getAllByRole("listitem");
    expect(rows.at(-2)).toHaveTextContent("mardi 20");
    expect(rows.at(-1)).toHaveTextContent("mercredi 21");
    expect(rows.at(-1)).toHaveTextContent("Pas de plan pour ce jour : le calcul s'est arrêté avant");
    expect(screen.getByText("Semaine du samedi 17 octobre au mercredi 21 octobre")).toBeInTheDocument();
    const card = screen.getByRole("article", { name: "mardi 20" });
    expect(card).toHaveTextContent("La cause est expliquée dans Planning, onglet Semaine.");
  });
});
