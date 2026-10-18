import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import DayCards from "./DayCards";
import { DAY_CARDS, DEFAULT_LAYOUT, type IndicatorLayout, type ViewLayout } from "./layout";
import { TODAY, TOMORROW, WITHOUT_BATTERY, WITHOUT_INSIGHTS } from "./testViews";
import type { DayView } from "./types";

// Recharts mesure son conteneur, ce que jsdom ne sait pas faire : graphiques remplacés.
vi.mock("./Charts", () => {
  const chart = (name: string) => () => <p>{name}</p>;
  return { EnergyChart: chart("graphique"), SocChart: chart("soc"), GridChart: chart("réseau") };
});

// Sans le résumé (ses cartes ont leurs propres tests) : seules les cartes du catalogue du lot 5.3.
const WITHOUT_SUMMARY: ViewLayout = { order: [...DAY_CARDS], hidden: ["summary"] };

function renderCards(view: DayView, layout: ViewLayout = WITHOUT_SUMMARY, indicators: IndicatorLayout = DEFAULT_LAYOUT.indicators) {
  render(
    <I18nProvider>
      <DayCards view={view} layout={layout} indicators={indicators} />
    </I18nProvider>,
  );
}

const titles = () => screen.getAllByRole("article").map((card) => card.getAttribute("aria-label"));

describe("cartes d'une vue de jour", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("maison de référence : toutes les cartes, dans l'ordre", async () => {
    renderCards(TODAY);
    expect(await screen.findByText("réseau")).toBeInTheDocument();
    expect(titles()).toEqual([
      "Planning des équipements",
      "Batterie (SoC)",
      "Réseau",
      "Production et consommation",
      "Indicateurs du plan",
      "Pourquoi ce plan",
    ]);
  });

  it("sans batterie : ni graphique du SoC ni indicateurs de la batterie", async () => {
    renderCards(WITHOUT_BATTERY);
    expect(await screen.findByText("réseau")).toBeInTheDocument();
    expect(titles()).not.toContain("Batterie (SoC)");
    const indicators = screen.getByRole("article", { name: "Indicateurs du plan" });
    expect(within(indicators).queryByText("SoC en fin de journée")).toBeNull();
    expect(within(indicators).queryByText("Énergie passée par la batterie")).toBeNull();
  });

  it("sans piscine : pas de ligne de filtration dans la frise", () => {
    const rows = TODAY.timeline.rows.filter((row) => row.kind !== "runtime");
    renderCards({ ...TODAY, timeline: { ...TODAY.timeline, rows } });
    const timeline = screen.getByRole("article", { name: "Planning des équipements" });
    expect(within(timeline).queryByLabelText("Piscine")).toBeNull();
    expect(within(timeline).getByLabelText("Lave-linge")).toBeInTheDocument();
  });

  it("plan sans indicateurs ni explications : pas leurs cartes", () => {
    renderCards(WITHOUT_INSIGHTS);
    expect(titles()).not.toContain("Indicateurs du plan");
    expect(titles()).not.toContain("Pourquoi ce plan");
  });

  it("met en avant l'indicateur de l'objectif du calcul", () => {
    renderCards(TODAY);
    const card = screen.getByRole("article", { name: "Indicateurs du plan" });
    expect(within(card).getByText(/Le calcul vise l'autonomie/)).toBeInTheDocument();
    const main = card.querySelector(".indicator-main");
    expect(main).toHaveTextContent("Achat au réseau4,50 kWh");
    expect(card.querySelector(".indicator")).toBe(main); // en premier
    expect(within(card).getByText("1,23 €")).toBeInTheDocument();
    expect(within(card).queryByText(/CO₂/)).toBeNull(); // sans intensité du réseau
  });

  it("poids libres : aucun indicateur mis en avant", () => {
    renderCards({ ...TOMORROW, objective: "custom" });
    const card = screen.getByRole("article", { name: "Indicateurs du plan" });
    expect(card.querySelector(".indicator-main")).toBeNull();
    expect(card.querySelector(".indicator")).toHaveTextContent("Coût (achat moins revente)");
  });

  it("explications par équipement et texte de la recommandation", async () => {
    const user = userEvent.setup();
    renderCards(TODAY);
    const card = screen.getByRole("article", { name: "Pourquoi ce plan" });
    expect(within(card).getByText("Placé à 10h pour profiter du soleil.")).toBeInTheDocument();
    await user.click(within(card).getByText("Texte de la recommandation"));
    expect(within(card).getByText(/Chauffe-eau : 15h00/)).toBeVisible();
  });

  it("suit l'ordre et les cartes masquées de la disposition", async () => {
    renderCards(TODAY, {
      order: ["energy", "grid", "timeline", "summary", "soc", "indicators", "explanations"],
      hidden: ["soc", "explanations", "summary"],
    });
    expect(await screen.findByText("réseau")).toBeInTheDocument();
    expect(titles()).toEqual(["Production et consommation", "Réseau", "Planning des équipements", "Indicateurs du plan"]);
  });

  it("le résumé se place entre deux grilles de cartes", async () => {
    renderCards(TODAY, { order: ["timeline", "summary", "grid", "soc", "energy", "indicators", "explanations"], hidden: [] });
    expect(await screen.findByText("réseau")).toBeInTheDocument();
    const found = titles();
    expect(found[0]).toBe("Planning des équipements");
    expect(found.indexOf("Réseau")).toBeGreaterThan(found.indexOf("SoC / capacité"));
  });

  it("indicateur choisi et indicateurs masqués", () => {
    renderCards(TODAY, WITHOUT_SUMMARY, { highlight: "cost_eur", hidden: ["export_kwh"] });
    const card = screen.getByRole("article", { name: "Indicateurs du plan" });
    expect(card.querySelector(".indicator-main")).toHaveTextContent("Coût (achat moins revente)1,23 €");
    expect(within(card).queryByText("Surplus envoyé au réseau")).toBeNull();
    expect(within(card).getByText("Indicateur mis en avant choisi dans « Personnaliser ».")).toBeInTheDocument();
  });
});
