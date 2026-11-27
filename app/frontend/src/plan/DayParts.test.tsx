import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import Banners from "./Banners";
import SummaryCards from "./SummaryCards";
import { TODAY, TOMORROW, WITHOUT_BATTERY, WITHOUT_SOLAR, YESTERDAY } from "./testViews";
import type { DayView } from "./types";
import ViewHeader from "./ViewHeader";

function renderDay(view: DayView) {
  render(
    <I18nProvider>
      <ViewHeader view={view} />
      <Banners view={view} />
      <SummaryCards view={view} />
    </I18nProvider>,
  );
}

describe("vue d'un jour", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("Aujourd'hui : en-tête, bandeaux et cartes au relevé", () => {
    renderDay(TODAY);

    expect(screen.getByText(/Sèche-linge reporté au dimanche 18 octobre/)).toBeInTheDocument();

    const departure = screen.getByLabelText("Départ de la batterie");
    // Tuile : le chiffre et la pastille d'abord ; dessous, une ligne par information.
    expect(departure).not.toHaveAttribute("open");
    expect(within(departure).getByText("Batterie à minuit")).toHaveClass("plan-tile-title");
    expect(within(departure).getByText("50 %")).toHaveClass("plan-tile-value");
    const line = (tile: HTMLElement, label: string) => within(tile).getByText(label).closest("div");
    expect(line(departure, "Mesuré à 0 h")).toHaveTextContent("Mesuré à 0 h2,56 kWh · 50 %");
    expect(line(departure, "Écart")).toHaveTextContent("Écart+1 pts");
    expect(line(departure, "Dernière charge à 100 %")).toHaveTextContent("Dernière charge à 100 %avant-hier");
    expect(within(departure).getByText("conforme")).toHaveClass("badge-ok");

    const weather = screen.getByLabelText("Météo");
    expect(line(weather, "Météo")).toHaveTextContent("MétéoJournée ensoleillée");
    expect(line(weather, "Mesuré au relevé")).toHaveTextContent("Mesuré au relevé6,5 kWh");
    expect(line(weather, "Dernière prévision")).toHaveTextContent("Dernière prévision6,0 kWh · +8 %");
    expect(line(weather, "Plein soleil")).toHaveTextContent("Plein soleil8h – 18h");
    expect(within(weather).getByText("prévision fiable · +8 %")).toHaveClass("badge-ok");

    const equipment = screen.getByLabelText("Équipements");
    // Une ligne par appareil : son nom, où il en est, son énergie.
    expect(within(equipment).getByText("Lave-linge").closest("li")).toHaveTextContent(
      "Lave-lingelancé à 10h051,30 kWh (+30 %)",
    );
    expect(within(equipment).getByText("Chauffe-eau").closest("li")).toHaveTextContent("Chauffe-eauprévu à 15h00");

    const soc = screen.getByRole("article", { name: "SoC / capacité" });
    expect(soc).toHaveTextContent("Au relevé");
    // L'estimé de cette ligne est la prévision du premier calcul du jour, pas celle du relevé :
    // le libellé le dit (« Estimé 5,00 kWh » sous « Estimé 7,10 kWh », constaté le 13/11/2026).
    expect(soc).toHaveTextContent("Journée (première prévision)");
    expect(within(soc).getAllByText("▲ +25%")[0]).toHaveClass("trend-good");
    const grid = screen.getByRole("article", { name: "Réseau" });
    expect(within(grid).getByText("▲ +25%")).toHaveClass("trend-bad"); // plus d'achat : défavorable
    expect(within(grid).getByText("▲")).toBeInTheDocument(); // estimé nul : flèche seule
    expect(grid).not.toHaveTextContent("∞");
  });

  it("Hier : pas de ligne « Journée » dans les cartes", () => {
    renderDay(YESTERDAY);

    expect(screen.getByRole("article", { name: "Production" })).not.toHaveTextContent("Journée");
  });

  it("Demain : une valeur prévue par carte, et les appareils prévus sans bilan au relevé", () => {
    renderDay({ ...TOMORROW, timeline: { ...TOMORROW.timeline, statuses: [], unplanned: [], badge: null } });

    // Pas de bilan (rien n'est mesuré), mais la tuile liste les créneaux prévus de la frise.
    const equipment = screen.getByLabelText("Équipements");
    const cycles = TOMORROW.timeline.rows
      .filter((row) => row.kind === "cycle")
      .flatMap((row) => row.planned.filter((bar) => !bar.carried));
    const count = cycles.length === 1 ? "1 prévu" : `${cycles.length} prévus`;
    expect(within(equipment).getByText(cycles.length === 0 ? "Rien de prévu" : count)).toHaveClass("plan-tile-value");
    expect(equipment).not.toHaveTextContent("lancé");
    expect(screen.getByRole("article", { name: "SoC max" })).toHaveTextContent("5,00 kWh 98 % · 16h");
    expect(within(screen.getByLabelText("Météo")).getByText("Par rapport à aujourd'hui").closest("div")).toHaveTextContent(
      "Par rapport à aujourd'hui−12 % · 9,5 kWh",
    );
    expect(within(screen.getByLabelText("Départ de la batterie")).getByText("fiable")).toBeInTheDocument();
  });

  it("Hier : « 3 lancés », sans « 0 prévus »", () => {
    const [first] = TODAY.timeline.statuses;
    const started = (device: string) => ({ ...first, device, status: "on_time" as const, actual_start_min: 600, actual_kwh: 1 });
    renderDay({
      ...YESTERDAY,
      timeline: { ...YESTERDAY.timeline, statuses: [started("A"), started("B"), started("C")], unplanned: [] },
    });

    expect(within(screen.getByLabelText("Équipements")).getByText("3 lancés")).toHaveClass("plan-tile-value");
  });

  it("la nuit, trop tôt pour juger : la tuile du soleil ne compare pas 0,0 kWh à 0,0 kWh", () => {
    const weather = { ...TODAY.cards!.weather!, badge: "too_early" as const, measured_kwh: 0, estimated_kwh: 0 };
    renderDay({ ...TODAY, cards: { ...TODAY.cards!, weather } });

    const tile = screen.getByLabelText("Météo");
    expect(within(tile).getByText(/trop tôt pour juger/)).toBeInTheDocument();
    expect(within(tile).queryByText("Mesuré au relevé")).toBeNull();
    expect(within(tile).queryByText("Dernière prévision")).toBeNull();
  });

  it("sans météo connue : pas de ligne « Météo » (elle disait « Production »)", () => {
    const weather = { ...TOMORROW.weather!, quality: null, share_percent: null, best_kwh: null, best_days: null };
    renderDay({ ...TOMORROW, weather });

    const tile = screen.getByLabelText("Météo");
    expect(within(tile).queryByText("Production")).toBeNull();
    expect(within(tile).queryByText("Journée ensoleillée")).toBeNull();
  });

  it("un jour à venir sans appareil : « prévu » seul, pas « ni lancé »", () => {
    const timeline = { ...TOMORROW.timeline, rows: [], statuses: [], unplanned: [], badge: null };
    renderDay({ ...TOMORROW, timeline });

    const tile = screen.getByLabelText("Équipements");
    expect(within(tile).getByText("Aucun équipement prévu")).toBeInTheDocument();
    expect(tile).not.toHaveTextContent("ni lancé");
  });

  it("sans batterie : ni départ ni cartes de la batterie", () => {
    renderDay(WITHOUT_BATTERY);

    expect(screen.queryByLabelText("Départ de la batterie")).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "SoC / capacité" })).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Batterie" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Réseau" })).toBeInTheDocument();
  });

  it("montre la consommation de la maison entre Réseau et Production, estimée et mesurée", () => {
    renderDay(TODAY);

    const cards = screen.getAllByRole("article").map((card) => card.getAttribute("aria-label"));
    expect(cards.slice(cards.indexOf("Réseau"), cards.indexOf("Réseau") + 3)).toEqual([
      "Réseau",
      "Consommation",
      "Production",
    ]);
    const card = screen.getByRole("article", { name: "Consommation" });
    // Au relevé : 4,00 estimés, 4,40 mesurés, plus que prévu (défavorable) ; puis la journée.
    expect(card).toHaveTextContent("4,00 kWh4,40 kWh▲ +10%");
    expect(card.querySelector(".trend-bad")).not.toBeNull();
    expect(card).toHaveTextContent("9,00 kWh9,60 kWh");
    // Trois cartes hors batterie : un tiers chacune, pas la moitié.
    expect(card).not.toHaveClass("summary-half");
  });

  it("sans solaire : ni bandeau météo ni carte de production", () => {
    renderDay(WITHOUT_SOLAR);

    expect(screen.queryByLabelText("Météo")).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Production" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Réseau" })).toBeInTheDocument();
  });
});
