import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { TODAY } from "./testViews";
import TimelineCard from "./TimelineCard";
import type { Timeline } from "./types";

function renderTimeline(timeline: Timeline, readingHour: number | null = 14.5) {
  render(
    <I18nProvider>
      <TimelineCard timeline={timeline} readingHour={readingHour} />
    </I18nProvider>,
  );
}

/** Piste de ``width`` pixels, donnée dès l'observation comme le fait un vrai ResizeObserver. */
function stubTrackWidth(width: number) {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly callback: () => void) {}
      observe() {
        this.callback();
      }
      disconnect() {}
    },
  );
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width } as DOMRect);
}

describe("frise des équipements", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("une ligne par équipement, prévu et réel, positionnés sur 24 heures", () => {
    renderTimeline(TODAY.timeline);

    const card = screen.getByRole("article", { name: "Planning des équipements" });
    const washer = within(card).getByLabelText("Lave-linge");
    const planned = within(washer).getByRole("button", { name: "Prévu 10h → 11h30 : Lave-linge, 1,00 kWh" });
    expect(planned).toHaveClass("tl-planned");
    expect(planned.style.left).toBe(`${(10 / 24) * 100}%`);
    expect(within(washer).getByRole("button", { name: "Réel 10h05 → 11h30 : Lave-linge, 1,30 kWh" })).toHaveClass(
      "tl-actual",
    );

    const battery = within(card).getByLabelText("Batterie");
    expect(within(battery).getByRole("button", { name: "Prévu 9h → 13h : charge, 2,00 kWh" })).toBeInTheDocument();
    const pool = within(card).getByLabelText("Piscine");
    expect(within(pool).getAllByRole("button")).toHaveLength(1);
    expect(within(pool).getByRole("button", { name: /mode eco/ })).toBeInTheDocument();
    expect(card.querySelectorAll(".tl-now")).toHaveLength(3);
  });

  it("écrit l'énergie dans les blocs assez larges, sans légende", () => {
    stubTrackWidth(960); // 40 px par heure
    renderTimeline(TODAY.timeline);

    const card = screen.getByRole("article", { name: "Planning des équipements" });
    const battery = within(card).getByLabelText("Batterie");
    expect(within(battery).getByRole("button", { name: "Prévu 9h → 13h : charge, 2,00 kWh" })).toHaveTextContent(
      "2,0 kWh",
    );
    expect(within(battery).getByRole("button", { name: /^Réel 9h15/ })).toHaveTextContent("2,1 kWh");
    expect(card.querySelector(".tl-legend")).toBeNull();
    expect(within(card).queryByText("prévu")).toBeNull();
  });

  it("centre l'énergie mesurée sur la partie du bloc que les décharges ne recouvrent pas", () => {
    stubTrackWidth(960); // 40 px par heure
    const battery = {
      device: "Batterie",
      kind: "battery",
      planned: [],
      // Charge de 9h à 15h, recouverte par deux décharges : 9h–12h30 visible (3,5 h), puis 13h–15h.
      actual: [
        { start_hour: 9, end_hour: 15, energy_kwh: 2, action: "charge", mode: null },
        { start_hour: 12.5, end_hour: 13, energy_kwh: 0.1, action: "discharge", mode: null },
        { start_hour: 14.5, end_hour: 14.75, energy_kwh: 0.1, action: "discharge", mode: null },
      ],
    } as unknown as Timeline["rows"][number];
    renderTimeline({ ...TODAY.timeline, rows: [battery] });

    const charge = screen.getByRole("button", { name: /^Réel 9h → 15h/ });
    const value = charge.querySelector(".tl-value") as HTMLElement;
    expect(value).toHaveTextContent("2,0 kWh");
    expect(value.style.left).toBe(`${((10.75 - 9) / 6) * 100}%`); // milieu de 9h–12h30
    expect(charge).toHaveClass("tl-actual");
  });

  it("centre aussi l'énergie prévue dans son bloc", () => {
    stubTrackWidth(960);
    renderTimeline(TODAY.timeline);

    const planned = screen.getByRole("button", { name: "Prévu 9h → 13h : charge, 2,00 kWh" });
    expect((planned.querySelector(".tl-value") as HTMLElement).style.left).toBe("50%");
  });

  it("laisse vides les blocs trop étroits pour leur énergie", () => {
    stubTrackWidth(240); // 10 px par heure : 4 heures font 40 px
    renderTimeline(TODAY.timeline);

    expect(document.querySelectorAll(".tl-value")).toHaveLength(0);
  });

  it("affiche le détail d'une barre au toucher", async () => {
    const user = userEvent.setup();
    renderTimeline(TODAY.timeline, null);

    await user.click(screen.getByRole("button", { name: /^Réel 9h15/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Réel 9h15 → 13h30 : charge, 2,10 kWh");
    expect(document.querySelector(".tl-now")).toBeNull();
  });

  it("explique une journée sans équipement planifié", () => {
    renderTimeline({ ...TODAY.timeline, rows: [], empty: "no_surplus" });
    expect(screen.getByText(/Pas de surplus solaire prévu \(production 10,0 kWh, consommation 9,6 kWh\)/)).toBeInTheDocument();
  });
});
