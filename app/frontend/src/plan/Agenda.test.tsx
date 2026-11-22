// Agenda d'un jour (lot 6b.4).

import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import Agenda from "./Agenda";
import { agenda, firstUpcoming, sunWindow } from "./agendaEntries";
import { TODAY } from "./testViews";
import type { DayView } from "./types";

const TOMORROW: DayView = { ...TODAY, kind: "tomorrow" };

describe("construction de l'agenda", () => {
  it("lit la frise prévue comme des actions datées, triées par heure", () => {
    const entries = agenda(TOMORROW); // jour à venir : rien de mesuré, tout vient du plan
    expect(entries.map((entry) => [entry.kind, entry.minute])).toEqual([
      ["battery_charge", 540],
      ["cycle", 600],
      ["runtime", 660],
      ["battery_max", 960],
    ]);
    expect(entries[2]).toMatchObject({ device: "Piscine", end: 900, mode: "eco" });
  });

  it("n'annonce pas la fin d'un cycle commencé la veille, et garde la fin le lendemain", () => {
    const view: DayView = {
      ...TODAY,
      timeline: {
        ...TODAY.timeline,
        rows: [
          {
            device: "Chauffe-eau",
            kind: "cycle",
            planned: [
              { start_hour: 0, end_hour: 1, energy_kwh: 0.6, action: null, mode: null, carried: true },
              { start_hour: 22, end_hour: 25, energy_kwh: 3, action: null, mode: null },
            ],
            actual: [],
          },
        ],
      },
    };
    const cycles = agenda(view).filter((entry) => entry.kind === "cycle");
    expect(cycles.map((entry) => [entry.minute, entry.end])).toEqual([[1320, 1500]]);
  });

  it("joint son explication à chaque appareil", () => {
    const view = { ...TODAY, explanations: [{ device: "Lave-linge", text: "Au plus fort du soleil." }] };
    expect(agenda(view)[1]).toMatchObject({ device: "Lave-linge", explanation: "Au plus fort du soleil." });
  });

  it("à la même heure : les appareils, puis le maximum de la batterie avant son relais", () => {
    const [battery, washer] = TODAY.timeline.rows;
    const view: DayView = {
      ...TOMORROW,
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

  it("aujourd'hui : la batterie d'après ses mesures jusqu'au relevé, d'après le plan ensuite", () => {
    // Relevé à 14 h 30. Charge prévue de 9 h à 16 h, mesurée de 9 h 15 à 14 h 15 : une seule
    // ligne, du début mesuré à la fin prévue ; le relais du soir reste celui du plan.
    const [battery, ...others] = TODAY.timeline.rows;
    const view: DayView = {
      ...TODAY,
      timeline: {
        ...TODAY.timeline,
        rows: [
          {
            ...battery,
            planned: [
              { start_hour: 9, end_hour: 16, energy_kwh: 3, action: "charge", mode: null },
              { start_hour: 19, end_hour: 23, energy_kwh: 2, action: "discharge", mode: null },
            ],
            actual: [
              { start_hour: 9.25, end_hour: 14.25, energy_kwh: 2.1, action: "charge", mode: null },
              { start_hour: 12, end_hour: 12.1, energy_kwh: 0.02, action: "discharge", mode: null }, // trop petit
            ],
          },
          ...others,
        ],
      },
    };
    const moves = agenda(view).filter((entry) => entry.kind === "battery_charge" || entry.kind === "battery_discharge");
    expect(moves.map((entry) => [entry.kind, entry.minute, "end" in entry ? entry.end : null])).toEqual([
      ["battery_charge", 555, 960],
      ["battery_discharge", 1140, 1380],
    ]);
  });

  it("hier : le plus haut niveau vient des mesures, à sa place parmi les phases mesurées", () => {
    // 22/11/2026 : le plan gardé prévoyait la décharge dès 15 h, la batterie a chargé jusqu'à
    // 16 h ; l'agenda disait « 15 h prend le relais » puis « 16 h au plus haut ».
    const [battery, ...others] = TODAY.timeline.rows;
    const view: DayView = {
      ...TODAY,
      kind: "yesterday",
      summary: { ...TODAY.summary, soc_max_hour: 15, soc_max_percent: 55 },
      hours: TODAY.hours.map((hour) => ({
        ...hour,
        soc_percent: hour.hour === 14 ? 55 : 20,
        soc_actual_percent: hour.hour === 15 ? 60 : hour.hour < 15 ? 20 + hour.hour : 30,
      })),
      timeline: {
        ...TODAY.timeline,
        rows: [
          {
            ...battery,
            planned: [
              { start_hour: 9, end_hour: 15, energy_kwh: 3, action: "charge", mode: null },
              { start_hour: 15, end_hour: 24, energy_kwh: 2, action: "discharge", mode: null },
            ],
            actual: [
              { start_hour: 9.25, end_hour: 16, energy_kwh: 3.2, action: "charge", mode: null },
              { start_hour: 16, end_hour: 22, energy_kwh: 2.4, action: "discharge", mode: null },
            ],
          },
          ...others,
        ],
      },
    };
    const battery_story = agenda(view)
      .filter((entry) => entry.kind.startsWith("battery"))
      .map((entry) => [entry.kind, entry.minute]);
    expect(battery_story).toEqual([
      ["battery_charge", 555],
      ["battery_max", 960],
      ["battery_discharge", 960],
    ]);
    expect(agenda(view).find((entry) => entry.kind === "battery_max")).toMatchObject({ percent: 60 });
  });

  it("place le plus haut niveau juste avant une décharge commencée dans la même heure", () => {
    // Le niveau n'est connu qu'en fin d'heure (18 h) ; la décharge mesurée commence à 17 h 55.
    const [battery, ...others] = TODAY.timeline.rows;
    const view: DayView = {
      ...TODAY,
      kind: "yesterday",
      hours: TODAY.hours.map((hour) => ({
        ...hour,
        soc_percent: 20,
        soc_actual_percent: hour.hour === 17 ? 100 : 40,
      })),
      timeline: {
        ...TODAY.timeline,
        rows: [
          {
            ...battery,
            planned: [],
            actual: [
              { start_hour: 9, end_hour: 17.8, energy_kwh: 4, action: "charge", mode: null },
              { start_hour: 17.92, end_hour: 21.5, energy_kwh: 4, action: "discharge", mode: null },
            ],
          },
          ...others,
        ],
      },
    };
    const story = agenda(view)
      .filter((entry) => entry.kind.startsWith("battery"))
      .map((entry) => [entry.kind, entry.minute]);
    expect(story).toEqual([
      ["battery_charge", 540],
      ["battery_max", 1075],
      ["battery_discharge", 1075],
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

  // À droite d'un appareil : son énergie prévue, ou « lancé · … » une fois vu dans les mesures.
  const washer = TODAY.timeline.statuses.find((status) => status.device === "Lave-linge");
  const planned = TODAY.timeline.rows.find((row) => row.device === "Lave-linge")?.planned[0].energy_kwh ?? 0;
  const kwh1 = (value: number) => value.toFixed(2).replace(".", ","); // deux décimales, comme la tuile
  const energy =
    washer && washer.actual_start_min !== null
      ? `lancé · ${kwh1(washer.actual_kwh ?? planned)} kWh`
      : `${kwh1(planned)} kWh`;

  function renderAgenda(view: DayView) {
    return render(
      <I18nProvider>
        <Agenda view={view} />
      </I18nProvider>,
    );
  }

  it("liste la journée, une ligne par événement : l'heure, ce qui se passe, la fin ou l'énergie", () => {
    renderAgenda(TOMORROW);
    expect(screen.getByRole("heading", { name: "La journée" })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Agenda de la journée" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "9hLa batterie se chargejusqu'à 13h",
      `10hLave-linge ${energy}Placé à 10h pour profiter du soleil.`,
      "11hPiscine, 4hVitesse eco",
      "16hBatterie au plus haut, 98 %",
    ]);
    // La raison du créneau est repliée sous la ligne de l'appareil.
    expect(within(list).getByText("Lave-linge").closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByText("Maintenant")).toBeNull(); // demain : pas de repère
  });

  it("dit quand il n'y a rien à lancer", () => {
    renderAgenda({ ...TOMORROW, battery_capacity_kwh: null, timeline: { ...TODAY.timeline, rows: [] } });
    expect(screen.getByText("Rien à lancer ce jour-là.")).toBeInTheDocument();
  });
});
