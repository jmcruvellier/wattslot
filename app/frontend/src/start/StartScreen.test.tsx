import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { TODAY } from "../plan/testViews";
import StartScreen, { type Setup } from "./StartScreen";

const NOT_READY: Setup = {
  ready: false,
  steps: [
    { key: "connection", state: "done", required: true, reason: null, params: {}, target: null },
    { key: "home", state: "todo", required: true, reason: "home_not_saved", params: {}, target: "home" },
    { key: "first_plan", state: "todo", required: true, reason: "no_plan_yet", params: {}, target: null },
    { key: "history", state: "waiting", required: false, reason: "history_importing", params: { count: "3" }, target: null },
    { key: "tariff", state: "todo", required: false, reason: "tariff_default", params: {}, target: "home#tariff" },
    { key: "battery", state: "not_applicable", required: false, reason: null, params: {}, target: null },
  ],
};

function renderScreen(onNavigate = vi.fn()) {
  render(
    <I18nProvider>
      <StartScreen onNavigate={onNavigate} />
    </I18nProvider>,
  );
  return onNavigate;
}

describe("StartScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("liste les étapes, dit pourquoi et ouvre le formulaire concerné", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json(NOT_READY));
    const onNavigate = renderScreen();

    // La liste détaillée est repliée sous les premiers pas guidés (lot 6b.6).
    await userEvent.click(await screen.findByText("Voir toutes les étapes"));
    const home = await screen.findByRole("listitem", { name: "Votre maison" });
    expect(home).toHaveTextContent("indispensable");
    expect(home).toHaveTextContent("Vérifiez les équipements proposés");
    expect(screen.getByRole("listitem", { name: "Historique de consommation" })).toHaveTextContent("3 compteur(s) restant(s)");
    expect(screen.queryByRole("listitem", { name: "Batterie" })).toBeNull(); // sans objet
    await userEvent.click(within(screen.getByRole("listitem", { name: "Tarif de l'électricité" })).getByRole("button", { name: "Y aller" }));
    expect(onNavigate).toHaveBeenCalledWith("home#tariff");
  });

  it("calcule le premier plan sur demande, puis relit la mise en route", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      calls.push(`${init?.method ?? "GET"} ${String(input)}`);
      return Response.json(NOT_READY);
    });
    renderScreen();

    await userEvent.click(await screen.findByText("Voir toutes les étapes"));
    await userEvent.click(await screen.findByRole("button", { name: "Calculer le plan maintenant" }));

    expect(calls).toContain("POST api/planning/run");
    expect(calls.filter((c) => c === "GET api/setup")).toHaveLength(2);
  });

  it("montre l'écran Aujourd'hui une fois la mise en route faite, le reste replié en tête", async () => {
    const ready: Setup = { ready: true, steps: [{ ...NOT_READY.steps[0] }, { ...NOT_READY.steps[4] }] };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input) === "api/setup" ? Response.json(ready) : Response.json(TODAY),
    );
    renderScreen();

    expect(await screen.findByText("Mise en route : 1 étape(s) facultative(s) à faire")).toBeInTheDocument();
    expect(await screen.findByText("En ce moment")).toBeInTheDocument();
  });

  it("ne montre plus la mise en route quand tout est fait", async () => {
    const done: Setup = { ready: true, steps: [{ ...NOT_READY.steps[0] }] };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input) === "api/setup" ? Response.json(done) : Response.json(TODAY),
    );
    renderScreen();

    expect(await screen.findByText("En ce moment")).toBeInTheDocument();
    expect(screen.queryByText(/Mise en route/)).not.toBeInTheDocument();
  });
});
