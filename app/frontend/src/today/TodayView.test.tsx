// Écran Aujourd'hui (lot 6b.3) : le moment, la prochaine action et ses boutons, la batterie, le
// soleil ; sans mesures, la recommandation du jour.

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { RUN_EVENT } from "../plan/planView";
import { TODAY } from "../plan/testViews";
import type { DayView, NextAction, Now } from "../plan/types";
import TodayView from "./TodayView";

const NOW: Now = {
  since: "2026-10-17T10:00:00Z",
  until: "2026-10-17T10:15:00Z",
  production_w: 1800,
  consumption_w: 2200,
  battery_w: -200,
  grid_w: 200,
  soc_percent: 64,
  off_peak: false,
  sentence: "Le soleil couvre 82 % de la maison",
};

const ACTION: NextAction = {
  device: "Lave-linge",
  start_min: 780,
  end_min: 900,
  explanation: "Au plus fort du soleil.",
  reminder: false,
  can_remind: true,
};

function mockApi(view: DayView | null, features: object | null = null) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/home/features" && features) return Response.json(features);
    if (url.startsWith("api/views/today")) {
      return view === null ? new Response(null, { status: 404 }) : Response.json(view);
    }
    if (url === "api/reminders" && init?.method === "POST") {
      return Response.json({ device: "Lave-linge", day: "2026-10-17" }, { status: 201 });
    }
    if (url === "api/planning/choices" && init?.method === "POST") {
      return Response.json(JSON.parse(String(init?.body)), { status: 201 });
    }
    if (url.startsWith("api/planning/choices/") && init?.method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    if (url === "api/planning/cancelled" && init?.method === "POST") {
      return Response.json(JSON.parse(String(init?.body)), { status: 201 });
    }
    if (url.startsWith("api/planning/cancelled/") && init?.method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    if (url === "api/planning/run" && init?.method === "POST") {
      return Response.json({}, { status: 200 });
    }
    return new Response(null, { status: 404 });
  });
}

function renderView() {
  return render(
    <I18nProvider>
      <TodayView />
    </I18nProvider>,
  );
}

describe("TodayView", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("résume le moment en une phrase et quatre flux", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: ACTION });
    renderView();
    const card = (await screen.findByRole("heading", { name: "Le soleil couvre 82 % de la maison" })).closest("section");
    const now = within(card as HTMLElement);
    expect(now.getByText("1,8 kW")).toBeInTheDocument();
    expect(now.getByText("2,2 kW")).toBeInTheDocument();
    expect(now.getByText("64 % · fournit 200 W")).toBeInTheDocument();
    expect(now.getByText("achat 200 W")).toBeInTheDocument();
  });

  it("affiche les puissances sous 1 kW en watts", async () => {
    mockApi({ ...TODAY, now: { ...NOW, production_w: 48, consumption_w: 0, battery_w: 288.4, grid_w: -999.6 }, next_action: ACTION });
    renderView();
    const card = (await screen.findByRole("heading", { name: "Le soleil couvre 82 % de la maison" })).closest("section");
    const now = within(card as HTMLElement);
    expect(now.getByText("48 W")).toBeInTheDocument();
    expect(now.getByText("0 W")).toBeInTheDocument();
    expect(now.getByText("64 % · charge 288 W")).toBeInTheDocument();
    expect(now.getByText(/1,0 kW/)).toBeInTheDocument();
  });

  it("montre la recommandation du jour sans mesures du moment", async () => {
    mockApi({ ...TODAY, now: { ...NOW, sentence: null }, recommendation: "Lancez le lave-linge à 13 h." });
    renderView();
    expect(await screen.findByRole("heading", { name: "Le plan du jour" })).toBeInTheDocument();
    expect(screen.getByText("Lancez le lave-linge à 13 h.")).toBeInTheDocument();
  });

  it("« C'est lancé » est noté par le serveur, et l'appareil suivant prend la place", async () => {
    // Le serveur garde le lancement déclaré : la vue relue donne l'appareil suivant, puis plus rien.
    const NEXT: NextAction = { ...ACTION, device: "Lave-vaisselle", start_min: 1320, end_min: 1400 };
    const launched: string[] = [];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("api/views/today")) {
        const next_action = [ACTION, NEXT].find((action) => !launched.includes(action.device)) ?? null;
        return Response.json({ ...TODAY, now: NOW, next_action, declared_launches: [...launched] });
      }
      if (url.startsWith("api/planning/launched/") && init?.method === "DELETE") {
        launched.splice(launched.indexOf(decodeURIComponent(url.split("/").pop() ?? "")), 1);
        return new Response(null, { status: 204 });
      }
      if (url === "api/planning/launched" && init?.method === "POST") {
        launched.push(JSON.parse(String(init.body)).device);
        return Response.json(JSON.parse(String(init.body)), { status: 201 });
      }
      return new Response(null, { status: 404 });
    });
    renderView();
    expect(await screen.findByRole("heading", { name: "Lancez Lave-linge" })).toBeInTheDocument();
    expect(screen.getByText(/Départ à 13h00, fin vers 15h00\. Au plus fort du soleil\./)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "C'est lancé" }));
    expect(await screen.findByRole("heading", { name: "Lancez Lave-vaisselle" })).toBeInTheDocument();
    expect(launched).toEqual(["Lave-linge"]);

    await userEvent.click(screen.getByRole("button", { name: "C'est lancé" }));
    expect(await screen.findByRole("heading", { name: "Rien à lancer d'ici ce soir" })).toBeInTheDocument();
    expect(launched).toEqual(["Lave-linge", "Lave-vaisselle"]);
    // Plus rien dans le navigateur : le lancement vaut aussi sur un autre appareil.
    expect(window.localStorage.length).toBe(0);
    expect(fetchMock).toHaveBeenCalled();

    // Clic par erreur : « Pas encore lancé » rend l'appareil à la prochaine action.
    expect(screen.getByText(/Lave-linge : marqué comme lancé\./)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Pas encore lancé" })[0]);
    expect(await screen.findByRole("heading", { name: "Lancez Lave-linge" })).toBeInTheDocument();
    expect(launched).toEqual(["Lave-vaisselle"]);
    expect(screen.getByText(/Lave-vaisselle : marqué comme lancé\./)).toBeInTheDocument();
  });

  it("dit quand le retour en arrière n'a pas abouti", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: null, declared_launches: ["Lave-linge"] }); // DELETE : 404
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Pas encore lancé" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Le retour en arrière n'a pas abouti.");
    expect(screen.getByText(/Lave-linge : marqué comme lancé\./)).toBeInTheDocument();
  });

  it("dit quand « C'est lancé » n'a pas pu être enregistré, et garde l'action", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: ACTION }); // la route du lancement répond 404
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "C'est lancé" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Le lancement n'a pas pu être enregistré.");
    expect(screen.getByRole("heading", { name: "Lancez Lave-linge" })).toBeInTheDocument();
  });

  it("dit pourquoi rien n'est à lancer", async () => {
    const idle = { ...TODAY, now: NOW, next_action: null };
    mockApi({ ...idle, idle_reason: "all_started" });
    const first = renderView();
    expect(await screen.findByRole("heading", { name: "Tout est lancé pour aujourd'hui" })).toBeInTheDocument();
    first.unmount();

    vi.restoreAllMocks();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    mockApi({ ...idle, idle_reason: "cancelled", timeline: { ...TODAY.timeline, cancelled: ["Lave-linge"] } });
    const second = renderView();
    expect(await screen.findByRole("heading", { name: "Rien à lancer : planification annulée" })).toBeInTheDocument();
    expect(screen.getByText(/Annulé pour aujourd'hui : Lave-linge\./)).toBeInTheDocument();
    second.unmount();

    vi.restoreAllMocks();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    mockApi({ ...idle, idle_reason: "nothing_planned" });
    renderView();
    expect(await screen.findByRole("heading", { name: "Aucun appareil prévu aujourd'hui" })).toBeInTheDocument();
  });

  it("propose une heure libre pour la prochaine action", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const fetchMock = mockApi({ ...TODAY, now: NOW, next_action: ACTION });
    const user = userEvent.setup();
    renderView();
    const hour = await screen.findByLabelText("Autre heure de départ :");
    await user.selectOptions(hour, "16");
    await user.click(screen.getByRole("button", { name: "Démarrer à 16h00" }));
    const post = fetchMock.mock.calls.find(([url]) => String(url) === "api/planning/choices");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ device: "Lave-linge", start_min: 960 });
    expect(fetchMock.mock.calls.some((call) => String(call[0]) === "api/planning/run")).toBe(true);
  });

  it("dit que l'heure prévue est passée, sans heure de fin", async () => {
    // Heure fixée : le choix « Autre heure de départ » propose les heures à venir de l'horloge
    // réelle. Chercher « 15h00 » dans toute la page faisait échouer le test de minuit à 15 h.
    vi.setSystemTime(new Date("2026-10-17T13:30:00"));
    mockApi({ ...TODAY, now: NOW, next_action: { ...ACTION, late: true } });
    renderView();
    expect(await screen.findByRole("heading", { name: "Lancez Lave-linge" })).toBeInTheDocument();
    expect(screen.getByText("Prochaine action · maintenant")).toBeInTheDocument();
    const sentence = screen.getByText(/Le départ prévu à 13h00 est passé : lancez-le dès que possible\. Au plus fort/);
    expect(sentence).not.toHaveTextContent("15h00");
  });

  it("ne garde pas « Rappel prévu » pour l'appareil suivant", async () => {
    let device = "Lave-linge";
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("api/views/today")) {
        return Response.json({ ...TODAY, now: NOW, next_action: { ...ACTION, device } });
      }
      if (url === "api/reminders" && init?.method === "POST") return Response.json({}, { status: 201 });
      if (url === "api/planning/launched" && init?.method === "POST") {
        device = "Lave-vaisselle";
        return Response.json({}, { status: 201 });
      }
      return new Response(null, { status: 404 });
    });
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Me le rappeler" }));
    expect(screen.getByRole("button", { name: "Rappel prévu" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "C'est lancé" }));
    expect(await screen.findByRole("heading", { name: "Lancez Lave-vaisselle" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Me le rappeler" })).toBeEnabled();
  });

  it("pose un rappel, et n'en propose pas sans service de notification", async () => {
    const fetch = mockApi({ ...TODAY, now: NOW, next_action: ACTION });
    const { unmount } = renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Me le rappeler" }));
    expect(screen.getByRole("button", { name: "Rappel prévu" })).toBeDisabled();
    const post = fetch.mock.calls.find(([url, init]) => url === "api/reminders" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ device: "Lave-linge" });
    unmount();

    vi.restoreAllMocks();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    mockApi({ ...TODAY, now: NOW, next_action: { ...ACTION, can_remind: false } });
    renderView();
    await screen.findByRole("heading", { name: "Lancez Lave-linge" });
    expect(screen.queryByRole("button", { name: /rappel/i })).not.toBeInTheDocument();
  });

  it("donne la batterie et le soleil du jour, avec leur tendance au relevé", async () => {
    // Total attendu : le mesuré puis le prévu (bandeau météo), jamais moins que le déjà produit ;
    // la somme des prévisions seules (10 kWh ici) donnait « 10 kWh prévus, 14 déjà produits ».
    mockApi({ ...TODAY, weather: { ...TODAY.weather, production_kwh: 16.5 }, now: NOW, next_action: null });
    renderView();
    expect(await screen.findByRole("heading", { name: "64 % en ce moment" })).toBeInTheDocument();
    expect(screen.getByText("Au plus haut vers 16h00 : 98 %.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "16,5 kWh prévus aujourd'hui" })).toBeInTheDocument();
    expect(screen.getByText("14,0 kWh déjà produits.")).toBeInTheDocument();
    // La référence de la pastille (+8 % : 6,5 kWh mesurés pour 6,0 prévus au relevé) est dite.
    expect(screen.getByText("6,0 kWh prévus à cette heure.")).toBeInTheDocument();
    // Tendances de TODAY : SoC +25 %, production +8 %, en pilule en tête de chaque carte.
    expect(screen.getAllByTitle("Écart avec la prévision au relevé")).toHaveLength(2);
    expect(screen.getByText("▲ +25%")).toHaveClass("trend-pill");
    expect(screen.getByText("▲ +8%")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rien à lancer d'ici ce soir" })).toBeInTheDocument();
  });

  it("sans mesure au relevé : pas d'indicateur de tendance", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: null, cards: null });
    renderView();
    expect(await screen.findByRole("heading", { name: "64 % en ce moment" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "9,5 kWh prévus aujourd'hui" })).toBeInTheDocument();
    expect(screen.queryByText(/[▲▼●]/)).not.toBeInTheDocument();
    expect(screen.queryByText(/prévus à cette heure/)).not.toBeInTheDocument();
  });

  it("sans solaire : pas de carte Soleil", async () => {
    mockApi({ ...TODAY, solar: false, now: NOW, next_action: null });
    renderView();
    expect(await screen.findByRole("heading", { name: "64 % en ce moment" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "9,5 kWh prévus aujourd'hui" })).not.toBeInTheDocument();
    expect(screen.queryByText("Soleil")).not.toBeInTheDocument();
  });

  it("sans appareil à placer : invite à en ajouter un", async () => {
    mockApi({ ...TODAY, now: NOW, next_action: null }, { solar: true, battery: false, appliances: 0 });
    const onNavigate = vi.fn();
    render(
      <I18nProvider>
        <TodayView onNavigate={onNavigate} />
      </I18nProvider>,
    );
    expect(await screen.findByRole("heading", { name: "Aucun appareil à placer" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ajouter un appareil" }));
    expect(onNavigate).toHaveBeenCalledWith("devices#add-device");
  });

  it("dit qu'un plan calculé pendant la reprise de l'historique est provisoire", async () => {
    mockApi({ ...TODAY, now: NOW, history_pending: 3 });
    renderView();
    expect(await screen.findByRole("note")).toHaveTextContent("Plan provisoire");
    expect(screen.getByRole("note")).toHaveTextContent("3 compteur(s) restant(s)");
  });

  it("signale une mesure impossible écartée du jour, avec les données à corriger", async () => {
    mockApi({ ...TODAY, now: NOW, discarded_hours: [9] });
    renderView();
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Mesure impossible écartée à 9 h : sans doute une coupure d'un capteur.");
    const link = screen.getByRole("link", { name: "Voir les données" });
    expect(link).toHaveAttribute("href", "#/home");
    await userEvent.click(link);
    expect(window.localStorage.getItem("home.tab")).toBe("data");
  });

  it("dit quand il n'y a pas encore de plan", async () => {
    mockApi(null);
    renderView();
    expect(await screen.findByText(/Pas encore de plan pour aujourd'hui/)).toBeInTheDocument();
  });

  it("change le créneau d'un équipement pas encore lancé depuis la frise", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const fetchMock = mockApi({
      ...TODAY,
      now: NOW,
      next_action: null,
      timeline: {
        ...TODAY.timeline,
        rows: [
          TODAY.timeline.rows[0],
          TODAY.timeline.rows[1],
          TODAY.timeline.rows[2],
          {
            device: "Sèche-linge",
            kind: "cycle",
            planned: [{ start_hour: 16, end_hour: 17, energy_kwh: 1, action: null, mode: null }],
            actual: [],
          },
        ],
      },
      explanations: [
        ...TODAY.explanations,
        {
          device: "Sèche-linge",
          text: "Placé à 16h.",
          explanation: {
            alternatives: [{ debut_min: 1140, ecart_cout_eur: -0.099, ecart_soutirage_kwh: -0.732 }],
            choisi: false,
          },
        },
      ],
    });
    const user = userEvent.setup();
    renderView();

    await user.click(await screen.findByRole("button", { name: "Prévu 16h → 17h : Sèche-linge, 1,00 kWh" }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByRole("heading", { name: "Départ de Sèche-linge" })).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: /Choisir le départ de 19h00/ }));

    const posts = fetchMock.mock.calls.filter((call) => String(call[0]) === "api/planning/choices");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(String((posts[0][1] as RequestInit).body))).toEqual({
      device: "Sèche-linge",
      start_min: 1140,
    });
    expect(fetchMock.mock.calls.some((call) => String(call[0]) === "api/planning/run")).toBe(true);
    // La feuille se ferme et la vue se relit (l'API du jour sert la même vue au test).
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("annule la planification de la prochaine action, sans quitter l'écran", async () => {
    vi.setSystemTime(new Date("2026-10-17T12:00:00"));
    const fetchMock = mockApi({ ...TODAY, now: NOW, next_action: ACTION });
    const user = userEvent.setup();
    renderView();

    await user.click(await screen.findByRole("button", { name: "Annuler" }));

    const posts = fetchMock.mock.calls.filter((call) => String(call[0]) === "api/planning/cancelled");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(String(posts[0][1]?.body))).toEqual({ device: "Lave-linge" });
    expect(fetchMock.mock.calls.some((call) => String(call[0]) === "api/planning/run")).toBe(true);
  });

  it("un rafraîchissement manqué garde la vue, avec un mot, jusqu'au suivant", async () => {
    let online = true;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).startsWith("api/views/today")) {
        return online ? Response.json({ ...TODAY, now: NOW }) : Response.json({}, { status: 502 });
      }
      return new Response(null, { status: 404 });
    });
    renderView();
    expect(await screen.findByText("Le soleil couvre 82 % de la maison")).toBeInTheDocument();

    online = false;
    act(() => {
      window.dispatchEvent(new Event(RUN_EVENT));
    });

    expect(await screen.findByText(/Rafraîchissement impossible/)).toBeInTheDocument();
    expect(screen.getByText("Le soleil couvre 82 % de la maison")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    online = true;
    act(() => {
      window.dispatchEvent(new Event(RUN_EVENT));
    });
    await waitFor(() => expect(screen.queryByText(/Rafraîchissement impossible/)).not.toBeInTheDocument());
  });
});
