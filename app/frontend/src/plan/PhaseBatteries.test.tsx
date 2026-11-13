// Plan calculé par phase : une ligne par groupe de batteries dans la frise, et la phase nommée
// dans l'agenda. Avec une seule ligne Batterie, rien ne change.

import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import Agenda from "./Agenda";
import { agenda } from "./agendaEntries";
import { TODAY } from "./testViews";
import TimelineCard from "./TimelineCard";
import type { DayView, TimelineRow } from "./types";

const group = (phase: number, action: "charge" | "discharge", start: number): TimelineRow => ({
  device: `Batterie ${phase}`,
  kind: "battery",
  phase,
  planned: [{ start_hour: start, end_hour: start + 2, energy_kwh: 1.5, action, mode: null }],
  actual: [],
});

const BY_PHASE: DayView = {
  ...TODAY,
  kind: "tomorrow",
  timeline: {
    ...TODAY.timeline,
    rows: [group(2, "charge", 10), group(3, "discharge", 19), group(0, "charge", 12)],
  },
};

describe("batteries par phase", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("nomme chaque ligne de batterie de la frise par sa phase", () => {
    render(
      <I18nProvider>
        <TimelineCard timeline={BY_PHASE.timeline} readingHour={null} />
      </I18nProvider>,
    );

    const card = screen.getByRole("article", { name: "Planning des équipements" });
    expect(within(card).getByLabelText("Batterie phase 2")).toBeInTheDocument();
    expect(within(card).getByLabelText("Batterie phase 3")).toBeInTheDocument();
    expect(within(card).getByLabelText("Batterie (total)")).toBeInTheDocument();
    expect(within(card).queryByLabelText("Batterie")).toBeNull();
  });

  it("garde le nom « Batterie » pour la ligne unique", () => {
    render(
      <I18nProvider>
        <TimelineCard timeline={TODAY.timeline} readingHour={null} />
      </I18nProvider>,
    );

    expect(screen.getByLabelText("Batterie")).toBeInTheDocument();
  });

  it("montre sous une ligne qui réunit plusieurs batteries le mesuré de chacune", () => {
    const measured = (action: "charge" | "discharge") => [
      { start_hour: 19, end_hour: 20, energy_kwh: 0.6, action, mode: null },
    ];
    const rows: TimelineRow[] = [
      {
        ...group(2, "charge", 10),
        batteries: [
          { key: "garage", name: "Batterie du garage", actual: measured("charge") },
          { key: "cellar", name: "Batterie du cellier", actual: measured("discharge") },
        ],
      },
      group(3, "discharge", 19),
    ];
    render(
      <I18nProvider>
        <TimelineCard timeline={{ ...TODAY.timeline, rows }} readingHour={20.5} />
      </I18nProvider>,
    );

    const card = screen.getByRole("article", { name: "Planning des équipements" });
    // Une batterie qui se vide dans l'autre, sur la même phase : chacune a sa ligne.
    const garage = within(card).getByLabelText("Batterie du garage (mesuré)");
    const cellar = within(card).getByLabelText("Batterie du cellier (mesuré)");
    expect(within(garage).getByRole("button", { name: "Réel 19h → 20h : charge, 0,60 kWh" })).toBeInTheDocument();
    expect(within(cellar).getByRole("button", { name: "Réel 19h → 20h : décharge, 0,60 kWh" })).toBeInTheDocument();
    // Pas de prévision par batterie : la ligne du groupe garde la sienne, seule.
    expect(within(garage).queryByRole("button", { name: /^Prévu/ })).toBeNull();
    expect(within(within(card).getByLabelText("Batterie phase 2")).getByRole("button", { name: /^Prévu/ })).toBeInTheDocument();
    // Un groupe d'une seule batterie n'a pas de ligne de plus.
    expect(within(card).getAllByLabelText(/\(mesuré\)$/)).toHaveLength(2);
  });

  it("dit dans l'agenda quelle batterie charge ou prend le relais", () => {
    expect(agenda(BY_PHASE).filter((entry) => entry.kind !== "battery_max")).toEqual([
      { kind: "battery_charge", minute: 600, end: 720, phase: 2 },
      { kind: "battery_charge", minute: 720, end: 840, phase: 0 },
      { kind: "battery_discharge", minute: 1140, end: 1260, phase: 3 },
    ]);

    render(
      <I18nProvider>
        <Agenda view={BY_PHASE} />
      </I18nProvider>,
    );

    expect(screen.getByText("Batterie phase 2 : charge")).toBeInTheDocument();
    expect(screen.getByText("Batterie (total) : charge")).toBeInTheDocument();
    expect(screen.getByText("Batterie phase 3 : prend le relais")).toBeInTheDocument();
    expect(screen.queryByText("La batterie se charge")).toBeNull();
  });
});
