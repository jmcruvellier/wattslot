import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { WeekChart } from "./Charts";
import { WEEK, WEEK_WITHOUT_BATTERY } from "./testViews";

// jsdom ne mesure rien : Recharts ne dessine pas, mais les graphiques se montent sans erreur.
describe("graphiques de la semaine", () => {
  it.each(["production", "consumption", "soc"] as const)("%s se monte", (series) => {
    const { container } = render(
      <I18nProvider>
        <WeekChart points={WEEK.points} series={series} nowIndex={WEEK.now_index} floor={WEEK.floor_percent} />
      </I18nProvider>,
    );
    expect(container.querySelector(".chart")).not.toBeNull();
  });

  it("SoC absent : se monte aussi", () => {
    const { container } = render(
      <I18nProvider>
        <WeekChart points={WEEK_WITHOUT_BATTERY.points} series="soc" nowIndex={null} floor={12} />
      </I18nProvider>,
    );
    expect(container.querySelector(".chart")).not.toBeNull();
  });
});
