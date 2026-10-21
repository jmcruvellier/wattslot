// Agenda d'un jour (lot 6b.4).

import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import Agenda, { DaySummaryCard } from "./Agenda";
import { agenda, firstUpcoming, sunWindow } from "./agendaEntries";
import { TODAY } from "./testViews";
import type { DayView } from "./types";

const TOMORROW: DayView = { ...TODAY, kind: "tomorrow" };

describe("construction de l'agenda", () => {
  it("lit la frise prévue comme des actions datées, triées par heure", () => {
    const entries = agenda(TODAY);
    expect(entries.map((entry) => [entry.kind, entry.minute])).toEqual([
      ["battery_charge", 540],
      ["cycle", 600],
      ["runtime", 660],
      ["battery_max", 960],
    ]);
    expect(entries[2]).toMatchObject({ device: "Piscine", end: 900, mode: "eco" });
  });

  it("joint son explication à chaque appareil", () => {
    const view = { ...TODAY, explanations: [{ device: "Lave-linge", text: "Au plus fort du soleil." }] };
    expect(agenda(view)[1]).toMatchObject({ device: "Lave-linge", explanation: "Au plus fort du soleil." });
  });

  it("à la même heure : les appareils, puis le maximum de la batterie avant son relais", () => {
    const [battery, washer] = TODAY.timeline.rows;
    const view: DayView = {
      ...TODAY,
      summary: { ...TODAY.summary, soc_max_hour: 15, soc_max_percent: 32 },
      timeline: {
        ...TODAY.timeline,
        rows: [
          {
            ...battery,
            planned: [
              { start_hour: 15, end_hour: 20, energy_kwh: 1, action: "discharge", mode: null },
              { start_hour: 9, end_hour: 15, energy_kwh: 2, action: "charge", mode: null },
            ],
          },
          { ...washer, planned: [{ start_hour: 15, end_hour: 16, energy_kwh: 1, action: null, mode: null }] },
        ],
      },
    };
    expect(agenda(view).map((entry) => [entry.kind, entry.minute])).toEqual([
      ["battery_charge", 540],
      ["cycle", 900],
      ["battery_max", 900],
      ["battery_discharge", 900],
    ]);
  });

  it("sans batterie ni rien à placer : un agenda vide", () => {
    const view = { ...TODAY, battery_capacity_kwh: null, timeline: { ...TODAY.timeline, rows: [] } };
    expect(agenda(view)).toEqual([]);
  });

  it("trouve la plage de soleil et la première action à venir", () => {
    expect(sunWindow(TODAY)).toEqual([8, 18]);
    expect(sunWindow({ ...TODAY, hours: TODAY.hours.map((h) => ({ ...h, production_kwh: 0 })) })).toBeNull();
    const entries = agenda(TODAY);
    expect(firstUpcoming(entries, 0)).toBe(0);
    expect(firstUpcoming(entries, 630)).toBe(2);
    expect(firstUpcoming(entries, 23 * 60)).toBe(entries.length);
  });
});

describe("Agenda", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderAgenda(view: DayView) {
    return render(
      <I18nProvider>
        <DaySummaryCard view={view} />
        <Agenda view={view} />
      </I18nProvider>,
    );
  }

  it("sans panneaux : pas de résumé du soleil", () => {
    renderAgenda({ ...TOMORROW, solar: false });
    expect(screen.queryByText(/kWh de soleil/)).toBeNull();
    expect(screen.getByRole("list", { name: "Agenda de la journée" })).toBeInTheDocument();
  });

  it("résume la journée et liste les actions", () => {
    renderAgenda(TOMORROW);
    expect(screen.getByRole("heading", { name: "Samedi, journée ensoleillée" })).toBeInTheDocument();
    expect(screen.getByText("10,0 kWh de soleil, surtout entre 8 h et 18 h")).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "Agenda de la journée" })).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "9h00La batterie se chargeJusqu'à 13h00",
      "10h00Lancez Lave-lingePlacé à 10h pour profiter du soleil.",
      "11h00Piscine, 4hVitesse eco",
      "16h00Batterie au plus haut, 98 %",
    ]);
    expect(screen.queryByText("Maintenant")).toBeNull(); // demain : pas de repère
  });

  it("dit quand il n'y a rien à lancer", () => {
    renderAgenda({ ...TOMORROW, battery_capacity_kwh: null, timeline: { ...TODAY.timeline, rows: [] } });
    expect(screen.getByText("Rien à lancer ce jour-là.")).toBeInTheDocument();
  });
});
