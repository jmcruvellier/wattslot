// État de charge de chaque batterie : carte « Batteries » de Planning, absente avec une seule.

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import BatteriesCard from "./BatteryList";
import { TODAY } from "./testViews";
import type { BatteryNow, DayView, Now } from "./types";

const NOW: Now = {
  since: null,
  until: null,
  production_w: null,
  consumption_w: null,
  battery_w: null,
  grid_w: null,
  soc_percent: 37,
  off_peak: false,
  sentence: null,
};

const battery = (name: string, change: Partial<BatteryNow>): BatteryNow => ({
  key: name,
  name,
  capacity_kwh: null,
  soc_percent: null,
  stored_kwh: null,
  power_w: null,
  ...change,
});

function renderCard(batteries: BatteryNow[]) {
  const view: DayView = { ...TODAY, now: { ...NOW, batteries } };
  return render(
    <I18nProvider>
      <BatteriesCard view={view} />
    </I18nProvider>,
  );
}

describe("carte Batteries", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  it("n'apparaît pas avec une seule batterie", () => {
    const { container } = renderCard([battery("Batterie", { soc_percent: 64 })]);

    expect(container).toBeEmptyDOMElement();
  });

  it("donne la charge, le contenu et l'activité de chaque batterie", () => {
    renderCard([
      battery("Batterie maison", { capacity_kwh: 5, soc_percent: 48, stored_kwh: 2.4, power_w: 1250, phase: "PhaseL2" }),
      battery("Batterie du garage", { capacity_kwh: 5, soc_percent: 23.4, stored_kwh: 1.17, power_w: -420, phase: "ThreePhases" }),
      battery("Batterie nomade", { soc_percent: 80, power_w: 0 }),
      battery("Batterie muette", {}),
    ]);

    const card = screen.getByRole("article", { name: "Batteries" });
    const cells = (name: RegExp) =>
      within(within(card).getByRole("row", { name })).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells(/Batterie maison/)).toEqual(["48 %", "2,4 kWh", "charge 1,3 kW"]);
    expect(cells(/Batterie du garage/)).toEqual(["23 %", "1,2 kWh", "fournit 420 W"]);
    expect(cells(/Batterie nomade/)).toEqual(["80 %", "—", "au repos"]);
    expect(cells(/Batterie muette/)).toEqual(["—", "—", "—"]);
    expect(within(card).getByRole("rowheader", { name: /Batterie maison/ })).toHaveTextContent("phase 2");
    expect(within(card).getByRole("rowheader", { name: /Batterie du garage/ })).toHaveTextContent("triphasée");
  });
});
