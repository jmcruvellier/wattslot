// Carte « Par phase » du jour : seulement quand le plan a été calculé par phase.

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import PhasesCard from "./PhasesCard";
import { TODAY } from "./testViews";
import type { DayView, PhaseDay } from "./types";

const PLANNED: PhaseDay[] = [
  { phase: 1, import_kwh: 12, export_kwh: 0 },
  { phase: 2, import_kwh: 4, export_kwh: 5.2 },
  { phase: 3, import_kwh: 7.25, export_kwh: 0 },
];

function renderCard(view: DayView) {
  return render(
    <I18nProvider>
      <PhasesCard view={view} />
    </I18nProvider>,
  );
}

describe("carte Par phase", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  it("n'apparaît pas quand le plan n'est pas calculé par phase", () => {
    const { container } = renderCard(TODAY);

    expect(container).toBeEmptyDOMElement();
  });

  it("dit ce que chaque phase achète et vend, prévu seulement sans capteur par phase", () => {
    renderCard({ ...TODAY, phases: PLANNED });

    const card = screen.getByRole("region", { name: "Par phase" });
    const row = within(card).getByRole("row", { name: /Phase 2/ });
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["4,0 kWh", "5,2 kWh"]);
    expect(within(card).queryByRole("columnheader", { name: "Acheté (mesuré)" })).toBeNull();
  });

  it("ajoute ce qui est mesuré, phase par phase", () => {
    const phases = PLANNED.map((phase) =>
      phase.phase === 2 ? { ...phase, import_actual_kwh: 1.5, export_actual_kwh: null } : phase,
    );
    renderCard({ ...TODAY, phases });

    const card = screen.getByRole("region", { name: "Par phase" });
    expect(within(card).getByRole("columnheader", { name: "Acheté (mesuré)" })).toBeInTheDocument();
    const cells = (name: RegExp) =>
      within(within(card).getByRole("row", { name })).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells(/Phase 2/)).toEqual(["4,0 kWh", "5,2 kWh", "1,5 kWh", "—"]);
    expect(cells(/Phase 1/)).toEqual(["12,0 kWh", "0,0 kWh", "—", "—"]);
  });
});
