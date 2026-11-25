import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import HourTiles from "./HourTiles";
import { HOURS } from "./testViews";
import type { HourPoint } from "./types";

function renderTiles(hours: HourPoint[], zone: number, readingHour: number | null = 14.5) {
  render(
    <I18nProvider>
      <HourTiles hours={hours} zone={zone} readingHour={readingHour} />
    </I18nProvider>,
  );
}

const tile = (label: string) => screen.getByText(label).closest(".tl-tile") as HTMLElement;

describe("tuiles de l'heure choisie", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("dit le mesuré de l'heure, et son écart au prévu quand il compte", () => {
    renderTiles(HOURS, 10);

    // Panneaux : 1 kWh prévu, 1 kWh mesuré : pas d'écart dit.
    expect(tile("Panneaux")).toHaveTextContent(/^Panneaux1,00 kWh$/);
    // Maison : 0,4 prévu, 0,5 mesuré : plus que prévu, défavorable.
    expect(tile("Maison")).toHaveTextContent("0,50 kWh ↑ 0,10");
    expect(tile("Maison").querySelector(".tl-tile-bad")).not.toBeNull();
    // Batterie et achat : pas de mesure dans l'exemple, le prévu est dit comme tel.
    expect(tile("Batterie")).toHaveTextContent("50 % Prévu");
    expect(tile("Achat")).toHaveTextContent("0,00 kWh Prévu");
  });

  it("marque l'heure choisie sur la courbe, pleine pour le mesuré et pointillée pour le prévu", () => {
    renderTiles(HOURS, 10);

    const zone = tile("Maison").querySelector(".tl-tile-zone") as SVGRectElement;
    expect(zone.getAttribute("x")).toBe("50"); // 10 h sur une courbe de 120 de large
    expect(tile("Maison").querySelectorAll(".tl-tile-line")).toHaveLength(2);
    expect(tile("Maison").querySelector(".tl-tile-planned")).not.toBeNull();
    // Achat : aucune heure mesurée, la courbe n'est que prévue.
    expect(tile("Achat").querySelectorAll(".tl-tile-line:not(.tl-tile-planned)")).toHaveLength(0);
  });

  it("pour une heure à venir ou en cours, dit le prévu, sans écart", () => {
    renderTiles(HOURS, 20);
    expect(tile("Maison")).toHaveTextContent("0,40 kWh Prévu");

    // L'heure en cours (13 h, relevé à 13 h 30) : son mesuré est encore partiel.
    renderTiles(HOURS, 13, 13.5);
    expect(screen.getAllByText("Maison")[1].closest(".tl-tile")).toHaveTextContent("0,40 kWh Prévu");
  });

  it("n'affiche pas de tuile pour ce que la maison n'a pas", () => {
    const bare = HOURS.map((point) => ({
      ...point,
      production_kwh: 0,
      production_actual_kwh: 0,
      soc_percent: null,
    }));
    renderTiles(bare, 10);

    expect(screen.queryByText("Panneaux")).toBeNull();
    expect(screen.queryByText("Batterie")).toBeNull();
    expect(screen.getByText("Maison")).toBeInTheDocument();
  });
});
