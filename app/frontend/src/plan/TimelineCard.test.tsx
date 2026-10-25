import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { TODAY } from "./testViews";
import TimelineCard from "./TimelineCard";
import { startChoices, type StartChoice } from "./startChoices";
import type { DayView, Timeline } from "./types";

type Call = { url: string; method: string; body: unknown };

/** Renvoie les appels passés, et répond aux changements de départ (choix, annulation, calcul). */
function mockChoices(): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body ? (JSON.parse(String(init.body)) as unknown) : null,
    });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    return Response.json({});
  });
  return calls;
}

function renderTimeline(
  timeline: Timeline,
  readingHour: number | null = 14.5,
  props: { choices?: Record<string, StartChoice>; onChanged?: () => void } = {},
) {
  render(
    <I18nProvider>
      <TimelineCard timeline={timeline} readingHour={readingHour} {...props} />
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
    vi.useRealTimers();
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

  // Sèche-linge prévu à 16h : deux autres départs à 18h et 19h.
  const FUTURE = {
    device: "Sèche-linge",
    kind: "cycle",
    planned: [{ start_hour: 16, end_hour: 17, energy_kwh: 1, action: null, mode: null }],
    actual: [],
  } as unknown as Timeline["rows"][number];
  const CHOICES: Record<string, StartChoice> = {
    "Sèche-linge": {
      alternatives: [
        { start_min: 1080, cost_eur_delta: 0.05, import_kwh_delta: 0.2 },
        { start_min: 1140, cost_eur_delta: -0.099, import_kwh_delta: -0.732 },
      ],
      chosen: false,
    },
  };

  it("sans choix possibles (autres jours), garde l'info-bulle au clic sur une prévision", async () => {
    const user = userEvent.setup();
    renderTimeline(TODAY.timeline, 14.5);

    await user.click(screen.getByRole("button", { name: "Prévu 10h → 11h30 : Lave-linge, 1,00 kWh" }));
    expect(screen.getByRole("status")).toHaveTextContent("Prévu 10h → 11h30 : Lave-linge, 1,00 kWh");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("ouvre la feuille aussi sur une prévision en cours ou passée, avec le bouton Annuler", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00")); // le Lave-linge prévu à 10h est lancé
    const user = userEvent.setup();
    renderTimeline(TODAY.timeline, 14.5, {
      choices: { "Lave-linge": { alternatives: [], chosen: false } },
      onChanged: () => undefined,
    });

    const planned = screen.getByRole("button", { name: "Prévu 10h → 11h30 : Lave-linge, 1,00 kWh" });
    expect(planned).toHaveClass("tl-pickable");
    await user.click(planned);

    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByRole("heading", { name: "Départ de Lave-linge" })).toBeInTheDocument();
    expect(within(sheet).getByText("Prévu 10h → 11h30 : 1,00 kWh")).toBeInTheDocument();
    // Sans autre départ proposé, la feuille propose d'annuler la planification.
    expect(within(sheet).queryByText("Autres départs possibles :")).toBeNull();
    expect(within(sheet).getByRole("button", { name: "Annuler le lancement" })).toBeInTheDocument();
  });

  it("ouvre la feuille des autres départs d'un équipement pas encore lancé", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const user = userEvent.setup();
    renderTimeline({ ...TODAY.timeline, rows: [FUTURE] }, 14.5, { choices: CHOICES, onChanged: () => undefined });

    const planned = screen.getByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" });
    expect(planned).toHaveClass("tl-pickable");
    await user.click(planned);

    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByRole("heading", { name: "Départ de Sèche-linge" })).toBeInTheDocument();
    expect(within(sheet).getByText("Prévu 16h → 17h : 1,00 kWh")).toBeInTheDocument();
    expect(within(sheet).getByText("Autres départs possibles :")).toBeInTheDocument();
    expect(within(sheet).getAllByRole("button", { name: /Choisir le départ de/ })).toHaveLength(2);
  });

  it("choisit un autre départ depuis la feuille, puis relance le calcul", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const calls = mockChoices();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    renderTimeline({ ...TODAY.timeline, rows: [FUTURE] }, 14.5, { choices: CHOICES, onChanged });

    await user.click(screen.getByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    await user.click(screen.getByRole("button", { name: /Choisir le départ de 19h00/ }));

    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["POST", "api/planning/choices"],
      ["POST", "api/planning/run"],
    ]);
    expect(calls[0].body).toEqual({ device: "Sèche-linge", start_min: 1140 });
    expect(onChanged).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull(); // la feuille se ferme, le plan recalcule
  });

  it("annule le départ choisi depuis la feuille (retour au choix du calcul)", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const calls = mockChoices();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    renderTimeline({ ...TODAY.timeline, rows: [FUTURE] }, 14.5, {
      choices: { "Sèche-linge": { alternatives: [], chosen: true } },
      onChanged,
    });

    await user.click(screen.getByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    await user.click(screen.getByRole("button", { name: "Revenir au choix du calcul" }));

    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["DELETE", "api/planning/choices/S%C3%A8che-linge"],
      ["POST", "api/planning/run"],
    ]);
    expect(onChanged).toHaveBeenCalled();
  });

  it("lit les autres départs dans les explications du plan du jour", () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const view = {
      ...TODAY,
      timeline: { ...TODAY.timeline, rows: [FUTURE] },
      explanations: [
        {
          device: "Sèche-linge",
          text: "Placé à 16h.",
          explanation: {
            alternatives: [
              { debut_min: 1140, ecart_cout_eur: -0.099, ecart_soutirage_kwh: -0.732 },
              { debut_min: 600, ecart_cout_eur: 0.4, ecart_soutirage_kwh: 1 }, // déjà passé : écarté
            ],
            choisi: true,
          },
        },
        // La batterie et la filtration (piscine) ne sont pas des cycles : jamais de feuille.
        { device: "Piscine", text: "Toute la journée." },
      ],
    } as unknown as DayView;

    expect(startChoices(view)).toEqual({
      "Sèche-linge": {
        alternatives: [{ start_min: 1140, cost_eur_delta: -0.099, import_kwh_delta: -0.732 }],
        chosen: true,
      },
    });
  });

  it("annule la planification depuis la feuille, puis la rétablit depuis la frise", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const calls = mockChoices();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    renderTimeline({ ...TODAY.timeline, rows: [FUTURE], cancelled: ["Lave-linge"] }, 14.5, {
      choices: { ...CHOICES, "Lave-linge": { alternatives: [], chosen: false } },
      onChanged,
    });

    // « Annuler » dans la feuille du départ.
    await user.click(screen.getByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    await user.click(screen.getByRole("button", { name: "Annuler le lancement" }));
    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["POST", "api/planning/cancelled"],
      ["POST", "api/planning/run"],
    ]);
    expect(calls[0].body).toEqual({ device: "Sèche-linge" });
    expect(onChanged).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();

    // « Rétablir » sous la frise, pour un équipement annulé plus tôt dans la journée.
    await user.click(screen.getByRole("button", { name: "Rétablir Lave-linge" }));
    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["POST", "api/planning/cancelled"],
      ["POST", "api/planning/run"],
      ["DELETE", "api/planning/cancelled/Lave-linge"],
      ["POST", "api/planning/run"],
    ]);
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("ne rétablit que sur la vue Aujourd'hui (sans choix possibles, rien n'est affiché)", () => {
    renderTimeline({ ...TODAY.timeline, rows: [FUTURE], cancelled: ["Lave-linge"] }, 14.5);
    expect(screen.queryByRole("button", { name: /Rétablir/ })).toBeNull();
  });
});
