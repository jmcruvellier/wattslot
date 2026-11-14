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
  props: { choices?: Record<string, StartChoice>; onChanged?: () => void; day?: string } = {},
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
    // jsdom arrondit les pourcentages du style à 4 décimales : on compare la valeur, pas le texte.
    expect(planned.style.left).toMatch(/%$/);
    expect(parseFloat(planned.style.left)).toBeCloseTo((10 / 24) * 100, 3);
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
    // Le prévu que le réel recouvre n'est qu'un crochet : son énergie est dans l'info-bulle.
    const planned = within(battery).getByRole("button", { name: "Prévu 9h → 13h : charge, 2,00 kWh" });
    expect(planned).not.toHaveClass("tl-upcoming");
    expect(planned).toHaveTextContent("");
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
    expect(value.style.left).toMatch(/%$/);
    expect(parseFloat(value.style.left)).toBeCloseTo(((10.75 - 9) / 6) * 100, 3); // milieu de 9h–12h30
    expect(charge).toHaveClass("tl-actual");
  });

  it("dessine en pilule, avec son énergie, le prévu à venir que rien de réel ne recouvre", () => {
    stubTrackWidth(960);
    const rows = TODAY.timeline.rows.map((row) => (row.kind === "battery" ? { ...row, actual: [] } : row));
    // Dernier relevé à 10 h : la charge prévue de 9 h à 13 h n'est pas finie.
    renderTimeline({ ...TODAY.timeline, rows }, 10);

    const planned = screen.getByRole("button", { name: "Prévu 9h → 13h : charge, 2,00 kWh" });
    expect(planned).toHaveClass("tl-upcoming");
    expect((planned.querySelector(".tl-value") as HTMLElement).style.left).toBe("50%");
    expect(document.querySelector(".tl-now-label")).toHaveTextContent("10h");
  });

  it("ne garde qu'un crochet pour le prévu passé que rien n'a réalisé", () => {
    stubTrackWidth(960);
    const rows = TODAY.timeline.rows.map((row) => (row.kind === "battery" ? { ...row, actual: [] } : row));
    renderTimeline({ ...TODAY.timeline, rows }, 14);

    const planned = screen.getByRole("button", { name: "Prévu 9h → 13h : charge, 2,00 kWh" });
    expect(planned).not.toHaveClass("tl-upcoming");
    expect(planned.querySelector(".tl-value")).toBeNull();
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
  // Sèche-linge prévu à 10h mais jamais lancé : le créneau est passé, pas l'équipement.
  const MISSED = {
    ...FUTURE,
    planned: [{ start_hour: 10, end_hour: 11, energy_kwh: 1, action: null, mode: null }],
  };
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

  it("pas de feuille pour un équipement lancé ou en cours : son bloc reste une info-bulle", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00")); // le Lave-linge réel a commencé à 10h05
    const user = userEvent.setup();
    renderTimeline(TODAY.timeline, 14.5, {
      choices: { "Lave-linge": { alternatives: [], chosen: false } },
      onChanged: () => undefined,
    });

    await user.click(screen.getByRole("button", { name: "Prévu 10h → 11h30 : Lave-linge, 1,00 kWh" }));
    expect(screen.getByRole("status")).toHaveTextContent("Prévu 10h → 11h30 : Lave-linge, 1,00 kWh");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("ouvre la feuille sur un créneau passé jamais lancé, avec le bouton Annuler", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const user = userEvent.setup();
    renderTimeline({ ...TODAY.timeline, rows: [MISSED] }, 14.5, {
      choices: { "Sèche-linge": { alternatives: [], chosen: false } },
      onChanged: () => undefined,
    });

    const planned = screen.getByRole("button", { name: "Prévu 10h → 11h : Sèche-linge, 1,00 kWh" });
    expect(planned).toHaveClass("tl-pickable");
    await user.click(planned);

    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByRole("heading", { name: "Départ de Sèche-linge" })).toBeInTheDocument();
    expect(within(sheet).getByText("Prévu 10h → 11h : 1,00 kWh")).toBeInTheDocument();
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

  it("choisit une heure libre pour aujourd'hui, seulement parmi les heures à venir", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const calls = mockChoices();
    const user = userEvent.setup();
    renderTimeline({ ...TODAY.timeline, rows: [FUTURE] }, 14.5, { choices: CHOICES, onChanged: vi.fn() });

    await user.click(screen.getByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    const hours = within(screen.getByRole("combobox", { name: "Autre heure de départ :" })).getAllByRole("option");
    expect(hours[0]).toHaveTextContent("13h00");
    await user.selectOptions(screen.getByRole("combobox"), "20");
    await user.click(screen.getByRole("button", { name: "Démarrer à 20h00" }));

    expect(calls[0].body).toEqual({ device: "Sèche-linge", start_min: 1200 });
  });

  it("change le départ d'un jour à venir (demain, J+2…) à toute heure, sans bouton Annuler", async () => {
    vi.setSystemTime(new Date("2026-10-17T22:00:00"));
    const calls = mockChoices();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    renderTimeline({ ...TODAY.timeline, rows: [FUTURE] }, null, {
      choices: { "Sèche-linge": { alternatives: [], chosen: true } },
      onChanged,
      day: "2026-10-18",
    });

    await user.click(screen.getByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).queryByRole("button", { name: "Annuler le lancement" })).toBeNull();
    expect(within(within(sheet).getByRole("combobox")).getAllByRole("option")).toHaveLength(24); // 0h à 23h
    await user.selectOptions(within(sheet).getByRole("combobox"), "1");
    await user.click(within(sheet).getByRole("button", { name: "Démarrer à 1h00" }));

    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ["POST", "api/planning/choices"],
      ["POST", "api/planning/run"],
    ]);
    expect(calls[0].body).toEqual({ device: "Sèche-linge", start_min: 60, day: "2026-10-18" });
    expect(onChanged).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    await user.click(screen.getByRole("button", { name: "Revenir au choix du calcul" }));
    expect(calls[2].url).toBe("api/planning/choices/S%C3%A8che-linge?day=2026-10-18");
  });

  it("coupe à minuit un cycle qui finit le lendemain, et montre la suite de celui de la veille", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const user = userEvent.setup();
    const heater = {
      device: "Chauffe-eau",
      kind: "cycle",
      planned: [
        { start_hour: 0, end_hour: 1, energy_kwh: 0.6, action: null, mode: null, carried: true },
        { start_hour: 22, end_hour: 25, energy_kwh: 3, action: null, mode: null },
      ],
      actual: [],
    } as unknown as Timeline["rows"][number];
    renderTimeline({ ...TODAY.timeline, rows: [heater] }, 14.5, {
      choices: { "Chauffe-eau": { alternatives: [], chosen: false } },
      onChanged: () => undefined,
    });

    const evening = screen.getByRole("button", { name: "Prévu 22h → 1h : Chauffe-eau, 3,00 kWh" });
    // De 22 h à minuit : 2/24 de la piste (l'écriture du nombre varie selon jsdom).
    expect(Number(/max\(3px, ([\d.]+)%\)/.exec(evening.style.width)?.[1])).toBeCloseTo(100 / 12, 3);
    expect(evening).toHaveClass("tl-pickable");
    const carried = screen.getByRole("button", { name: "Suite de la veille 0h → 1h : Chauffe-eau, 0,60 kWh" });
    expect(carried).not.toHaveClass("tl-pickable");
    await user.click(carried);
    expect(screen.queryByRole("dialog")).toBeNull();
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

  it("deux cycles du même équipement : une ligne, et chaque cycle a sa feuille et son Annuler", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const user = userEvent.setup();
    const calls = mockChoices();
    // Le premier lave-linge a tourné à 10h05 ; le second est prévu à 16h.
    const twice = {
      device: "Lave-linge",
      kind: "cycle" as const,
      planned: [
        { start_hour: 10, end_hour: 11.5, energy_kwh: 1, action: null, mode: null, cycle: "Lave-linge" },
        { start_hour: 16, end_hour: 17.5, energy_kwh: 1, action: null, mode: null, cycle: "Lave-linge #2" },
      ],
      actual: [{ start_hour: 10.0833, end_hour: 11.5, energy_kwh: 1, action: null, mode: null }],
    };
    const view = {
      ...TODAY,
      timeline: { ...TODAY.timeline, rows: [twice] },
      explanations: [
        { device: "Lave-linge", text: "Lancé à 10h05." },
        {
          device: "Lave-linge #2",
          text: "Placé à 16h.",
          explanation: { alternatives: [{ debut_min: 1080, ecart_cout_eur: 0.1, ecart_soutirage_kwh: 0.2 }] },
        },
      ],
    } as unknown as DayView;
    const choices = startChoices(view);
    expect(Object.keys(choices)).toEqual(["Lave-linge", "Lave-linge #2"]);
    expect(choices["Lave-linge #2"].alternatives).toHaveLength(1);

    renderTimeline(view.timeline, 14.5, { choices, onChanged: () => undefined });
    expect(screen.getAllByLabelText("Lave-linge")).toHaveLength(1); // une seule ligne

    // Le cycle déjà fait ne se déplace plus ; le second, pas encore lancé, s'ouvre.
    const done = screen.getByRole("button", { name: "Prévu 10h → 11h30 : Lave-linge, 1,00 kWh" });
    expect(done).not.toHaveClass("tl-pickable");
    const second = screen.getByRole("button", { name: "Prévu 16h → 17h30 : Lave-linge, 1,00 kWh" });
    expect(second).toHaveClass("tl-pickable");
    await user.click(second);

    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByRole("heading", { name: "Départ de Lave-linge #2" })).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Annuler le lancement" }));
    const cancelled = calls.find((call) => call.url.endsWith("api/planning/cancelled"));
    expect(cancelled?.body).toEqual({ device: "Lave-linge #2" });
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
