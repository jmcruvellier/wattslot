import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import Banners from "./Banners";
import SummaryCards from "./SummaryCards";
import { TODAY, TOMORROW, WITHOUT_BATTERY, WITHOUT_SOLAR, YESTERDAY } from "./testViews";
import type { DayView } from "./types";
import ViewHeader from "./ViewHeader";

function renderDay(view: DayView, onChanged = vi.fn()) {
  render(
    <I18nProvider>
      <ViewHeader view={view} onChanged={onChanged} />
      <Banners view={view} />
      <SummaryCards view={view} />
    </I18nProvider>,
  );
  return onChanged;
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

    expect(screen.getByRole("button", { name: "Calculer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rafraîchir les données réelles" })).toBeInTheDocument();
    expect(screen.getByText(/Sèche-linge reporté au dimanche 18 octobre/)).toBeInTheDocument();

    const departure = screen.getByLabelText("Départ de la batterie");
    expect(departure).toHaveTextContent("Départ à 0h : 2,56 kWh (50 %) mesuré");
    expect(departure).toHaveTextContent("(+1 pts)");
    expect(departure).toHaveTextContent("Dernière charge à 100 % : il y a 2 jours");
    expect(within(departure).getByText("conforme")).toHaveClass("badge-ok");

    const weather = screen.getByLabelText("Météo");
    expect(weather).toHaveTextContent("Journée ensoleillée");
    expect(weather).toHaveTextContent("au relevé : 6,5 kWh mesurés, +8 % par rapport à la dernière prévision (6,0 kWh)");
    expect(within(weather).getByText("prévision fiable")).toHaveClass("badge-ok");

    const equipment = screen.getByLabelText("Équipements");
    expect(equipment).toHaveTextContent("Lave-linge à l'heure (10h05), 1,30 kWh (+30 %)");
    expect(equipment).toHaveTextContent("Chauffe-eau prévu à 15h00");

    const soc = screen.getByRole("article", { name: "SoC / capacité" });
    expect(soc).toHaveTextContent("Au relevé");
    expect(soc).toHaveTextContent("Journée");
    expect(within(soc).getAllByText("▲ +25%")[0]).toHaveClass("trend-good");
    const grid = screen.getByRole("article", { name: "Réseau" });
    expect(within(grid).getByText("▲ +25%")).toHaveClass("trend-bad"); // plus d'achat : défavorable
    expect(within(grid).getByText("▲")).toBeInTheDocument(); // estimé nul : flèche seule
    expect(grid).not.toHaveTextContent("∞");
  });

  it("Hier : pas de bouton ni de ligne « Journée »", () => {
    renderDay(YESTERDAY);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Production" })).not.toHaveTextContent("Journée");
  });

  it("Demain : une valeur prévue par carte, pas de bilan des équipements", () => {
    renderDay(TOMORROW);

    expect(screen.getByRole("button", { name: "Calculer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rafraîchir les données réelles" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Équipements")).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "SoC max" })).toHaveTextContent("5,00 kWh 98 % · 16h");
    expect(screen.getByLabelText("Météo")).toHaveTextContent("-12 % par rapport à aujourd'hui (9,5 kWh prévus)");
    expect(within(screen.getByLabelText("Départ de la batterie")).getByText("fiable")).toBeInTheDocument();
  });

  it("sans batterie : ni départ ni cartes de la batterie", () => {
    renderDay(WITHOUT_BATTERY);

    expect(screen.queryByLabelText("Départ de la batterie")).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "SoC / capacité" })).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Batterie" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Réseau" })).toBeInTheDocument();
  });

  it("sans solaire : ni bandeau météo ni carte de production", () => {
    renderDay(WITHOUT_SOLAR);

    expect(screen.queryByLabelText("Météo")).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Production" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Réseau" })).toBeInTheDocument();
  });

  it("« Calculer » lance un calcul puis recharge la vue", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({}));
    const onChanged = renderDay(TODAY);

    await userEvent.click(screen.getByRole("button", { name: "Calculer" }));

    expect(fetchMock).toHaveBeenCalledWith("api/planning/run", { method: "POST" });
    expect(onChanged).toHaveBeenCalledOnce();
  });
});
