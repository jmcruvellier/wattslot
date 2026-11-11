import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { QualityBadge } from "./QualityBadge";
import type { ForecastQuality } from "./types";

const QUALITY: ForecastQuality = {
  level: "fair",
  score: 64,
  factors: [
    { code: "weather_horizon", level: "poor", params: { days: 5 } },
    { code: "consumption_history", level: "fair", params: { days: 6, target: 6, same_weekday: true, missing_hours: 2 } },
    { code: "consumption_regularity", level: "good", params: { percent: 12 } },
    { code: "solar_source", level: "fair", params: { fallback: true } },
    { code: "cycle_profiles", level: "fair", params: { devices: "Lave-linge", count: 1 } },
  ],
};

describe("QualityBadge", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  it("montre le niveau et explique chaque critère au clic", async () => {
    render(
      <I18nProvider>
        <QualityBadge quality={QUALITY} />
      </I18nProvider>,
    );
    const badge = screen.getByRole("button", { name: "Qualité des prévisions : Moyenne. Afficher le détail" });
    expect(badge).toHaveTextContent("Moyenne");

    await userEvent.click(badge);
    const dialog = screen.getByRole("dialog", { name: "Qualité des prévisions" });
    expect(within(dialog).getByText("Note : 64 sur 100")).toBeInTheDocument();
    expect(within(dialog).getByText("Météo : prévision à 5 jours, souvent loin de la réalité.")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Consommation habituelle : moyenne des 6 derniers mêmes jours de la semaine (6 attendus)."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("2 heures sur 24 sans assez de relevés (moins de 3 jours) : leur consommation est comptée à zéro."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Régularité : la consommation varie d'environ 12 % d'un jour à l'autre.")).toBeInTheDocument();
    expect(within(dialog).getByText(/estimée avec Open-Meteo/)).toBeInTheDocument();
    expect(within(dialog).getByText("Cycles des appareils : pas encore assez de cycles mesurés pour Lave-linge.")).toBeInTheDocument();
    // Le niveau de chaque critère est dit, pas seulement montré par la couleur.
    expect(within(dialog).getAllByRole("img", { name: "Faible" })).toHaveLength(1);
  });
});
