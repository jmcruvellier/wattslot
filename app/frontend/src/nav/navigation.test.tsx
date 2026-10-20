// Navigation de l'application (lot 6b.2) : sections par adresse, « précédent », sous-pages,
// liens du serveur et menu repliable.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { I18nProvider } from "../i18n/I18nProvider";
import { MENU_STORAGE_KEY } from "./menu";

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "api/setup") {
      return Response.json({
        ready: false,
        steps: [{ key: "tariff", state: "todo", target: "home#tariff", blocking: false }],
      });
    }
    return new Response(null, { status: 404 });
  });
}

function renderApp() {
  return render(
    <I18nProvider>
      <App />
    </I18nProvider>,
  );
}

function menu() {
  return within(screen.getByRole("navigation", { name: "Navigation principale" }));
}

describe("navigation", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    mockApi();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = "";
  });

  it("propose six sections et ouvre Aujourd'hui par défaut", () => {
    renderApp();
    const links = menu().getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Aujourd'hui",
      "Planning",
      "Courbes",
      "Ma maison",
      "Assistant",
      "Réglages",
    ]);
    expect(menu().getByRole("link", { name: "Aujourd'hui" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { level: 1, name: "Aujourd'hui" })).toBeInTheDocument();
  });

  it("ouvre les courbes à leur adresse", async () => {
    window.location.hash = "#/curves";
    renderApp();
    expect(screen.getByRole("heading", { level: 1, name: "Courbes" })).toBeInTheDocument();
    expect(menu().getByRole("link", { name: "Courbes" })).toHaveAttribute("aria-current", "page");
    expect(menu().getByRole("link", { name: "Courbes" })).toHaveAttribute("href", "#/curves");
  });

  it("ouvre la section de l'adresse, et revient à la précédente", async () => {
    window.location.hash = "#/assistant";
    renderApp();
    expect(screen.getByRole("heading", { level: 1, name: "Assistant" })).toBeInTheDocument();

    await userEvent.click(menu().getByRole("link", { name: "Réglages" }));
    await waitFor(() => expect(window.location.hash).toBe("#/settings"));
    expect(screen.getByRole("heading", { level: 1, name: "Réglages" })).toBeInTheDocument();

    window.history.back();
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "Assistant" })).toBeInTheDocument());
  });

  it("range les sous-pages sous « Pour aller plus loin », avec un retour", async () => {
    window.location.hash = "#/settings";
    const { container } = renderApp();
    // Les Réglages sont une liste (lot 6b.6) : l'état de l'application y est sous « Pour aller plus loin ».
    await userEvent.click(await screen.findByRole("link", { name: /État de l'application/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "État de l'application" })).toBeInTheDocument();
    expect(menu().getByRole("link", { name: "Réglages" })).toHaveAttribute("aria-current", "page");
    expect(container.querySelector(".back-link")).toHaveAttribute("href", "#/settings");
  });

  it("range les écrans experts de Ma maison dans l'onglet « Avancé »", async () => {
    window.location.hash = "#/home";
    renderApp();
    await userEvent.click(await screen.findByRole("tab", { name: "Avancé" }));
    const nav = await screen.findByRole("navigation", { name: "Pour aller plus loin" });
    const more = within(nav);
    expect(more.getByRole("heading", { level: 2, name: "Pour aller plus loin" })).toBeInTheDocument();
    // Avant le lexique.
    expect(nav.nextElementSibling?.querySelector("summary")).toHaveTextContent("Lexique");
    expect(more.getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Appareils et capteurs", "#/home/devices"],
      ["Modèles prêts à l'emploi", "#/home/templates"],
      ["Sauvegarder ou partager", "#/home/backup"],
      ["Graphe de la maison", "#/home/graph"],
      ["Bibliothèque d'appareils", "#/home/library"],
    ]);
  });

  it("mène une étape de la mise en route à sa nouvelle place", async () => {
    renderApp();
    const step = await screen.findByRole("listitem", { name: "Tarif de l'électricité" });
    await userEvent.click(within(step).getByRole("button"));
    await waitFor(() => expect(window.location.hash).toBe("#/home"));
    expect(screen.getByRole("heading", { level: 1, name: "Ma maison" })).toBeInTheDocument();
  });

  it("replie le menu et garde le choix", async () => {
    window.localStorage.setItem(MENU_STORAGE_KEY, "open");
    const { container, unmount } = renderApp();
    const shell = container.querySelector(".app-shell");
    expect(shell).toHaveAttribute("data-menu", "open");

    await userEvent.click(menu().getByRole("button", { name: "Replier le menu" }));
    expect(shell).toHaveAttribute("data-menu", "collapsed");
    expect(window.localStorage.getItem(MENU_STORAGE_KEY)).toBe("collapsed");
    // Replié, chaque section garde son nom pour les lecteurs d'écran et en infobulle.
    expect(menu().getByRole("link", { name: "Planning" })).toHaveAttribute("title", "Planning");
    unmount();

    renderApp();
    expect(menu().getByRole("button", { name: "Déplier le menu" })).toHaveAttribute("aria-expanded", "false");
  });
});
