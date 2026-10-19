// Chaque vue du plan dans chaque langue (lot 5.7) : aucune clé de catalogue ne reste à l'écran,
// et les langues chargées à la demande s'affichent une fois leur catalogue lu.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CurvesScreen from "../plan/CurvesScreen";
import PlanScreen from "../plan/PlanScreen";
import { TODAY, WEEK } from "../plan/testViews";
import { I18nProvider } from "./I18nProvider";
import { LANGUAGES, translate } from "./translate";

// Recharts mesure son conteneur, ce que jsdom ne sait pas faire : graphiques remplacés.
vi.mock("../plan/Charts", () => ({
  EnergyChart: () => null,
  SocChart: () => null,
  GridChart: () => null,
  WeekChart: () => null,
}));

// Une clé de catalogue affichée telle quelle : « plan.timeline.title »…
const RAW_KEY = /\b(app|plan|settings|nav|setup|objective)\.[a-z_]+(\.[a-z_]+)*\b/;

function mockApi() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "api/views/versions") return Response.json({ yesterday: 1, today: 1, tomorrow: 1, week: 1 });
    if (url.startsWith("api/views/week")) return Response.json(WEEK);
    if (url.startsWith("api/views/yesterday")) return Response.json({ ...TODAY, kind: "yesterday" });
    if (url.startsWith("api/views/tomorrow")) return Response.json({ ...TODAY, kind: "tomorrow", cards: null });
    if (url.startsWith("api/views/today")) return Response.json(TODAY);
    return Response.json({ detail: "not_found" }, { status: 404 });
  });
}

describe("vues du plan dans chaque langue", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Planning (agenda) et Courbes (cartes de la phase 5, sous « Personnaliser »).
  const SCREENS = [
    { name: "Planning", Screen: PlanScreen, title: "plan.title" },
    { name: "Courbes", Screen: CurvesScreen, title: "nav.curves" },
  ];
  for (const language of LANGUAGES) {
    for (const { name, Screen, title } of SCREENS) {
      it(`${language} : aucune clé brute dans ${name}, Hier, Aujourd'hui, Demain et Semaine`, async () => {
        const user = userEvent.setup();
        window.localStorage.setItem("wattslot.language", language);
        mockApi();
        render(
          <I18nProvider>
            <Screen />
          </I18nProvider>,
        );
        // Le titre dans la langue voulue : le catalogue est chargé.
        expect(await screen.findByRole("heading", { name: translate(language, title) })).toBeInTheDocument();
        for (const tab of ["yesterday", "today", "tomorrow", "week"] as const) {
          await user.click(screen.getByRole("tab", { name: translate(language, `plan.tabs.${tab}`) }));
          if (Screen === CurvesScreen) {
            await screen.findByRole("button", { name: translate(language, "plan.layout.open") });
          } else {
            await waitFor(() => expect(screen.queryByText(translate(language, "plan.loading"))).toBeNull());
          }
          expect(document.body.textContent ?? "", `${language} / ${tab}`).not.toMatch(RAW_KEY);
        }
      });
    }
  }

  it.each([
    ["de", "Tagesplan", "Heute"],
    ["nl", "Dagplan", "Vandaag"],
    ["es", "Plan del día", "Hoy"],
    ["it", "Piano del giorno", "Oggi"],
  ])("%s est bien traduit, pas en anglais de secours", async (language, title, today) => {
    window.localStorage.setItem("wattslot.language", language);
    mockApi();
    render(
      <I18nProvider>
        <PlanScreen />
      </I18nProvider>,
    );
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: today })).toBeInTheDocument();
  });
});
