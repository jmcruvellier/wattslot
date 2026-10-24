import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App, { type Health } from "./App";
import { I18nProvider } from "./i18n/I18nProvider";
import { RELEASES_URL } from "./nav/updates";

const HEALTH: Health = {
  version: "0.7.0",
  mode: "standalone",
  connections: {
    home_assistant: { state: "not_configured", version: null, error: null, error_code: null },
  },
};

// Réponses de l'API par adresse : l'état pour api/health, une mise en route vide sinon ; la
// dernière release du dépôt public si elle est donnée (sinon GitHub répond 404).
function mockApi(health: Health | Response, release?: { tag_name: string; html_url: string }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "api/health") return health instanceof Response ? health : Response.json(health);
    if (url === "api/setup") return Response.json({ steps: [], ready: false });
    if (url === RELEASES_URL && release) return Response.json(release);
    return new Response(null, { status: 404 });
  });
}

// Le diagnostic est une sous-page des réglages (lot 6b.2).
async function openDiagnostic() {
  await userEvent.click(await screen.findByRole("link", { name: "Settings" }));
  await userEvent.click(await screen.findByRole("link", { name: /App status/ }));
}

function renderApp() {
  return render(
    <I18nProvider>
      <App />
    </I18nProvider>,
  );
}

describe("App", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("affiche l'état de l'application dans le diagnostic", async () => {
    mockApi(HEALTH);

    renderApp();
    await openDiagnostic();

    expect(await screen.findByText("Standalone")).toBeInTheDocument();
    expect(screen.getByText("not configured")).toBeInTheDocument();
    expect(screen.getByText("Version 0.7.0")).toBeInTheDocument();
    expect(globalThis.fetch).toHaveBeenCalledWith("api/health", expect.anything());
  });

  it("signale une nouvelle version : point sur Réglages, encadré dans État de l'application", async () => {
    const notes = "https://github.com/jmcruvellier/wattslot/releases/tag/v0.9.0";
    mockApi(HEALTH, { tag_name: "v0.9.0", html_url: notes });

    renderApp();
    const settings = await screen.findByRole("link", { name: "Settings, New version available" });
    await userEvent.click(settings);
    expect(await screen.findByText("New version 0.9.0")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: /App status/ }));

    // En tête de page, hors du détail technique replié ; rappelée dans ce détail.
    const notice = await waitFor(() => {
      const found = document.querySelector(".update-banner");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(within(notice).getByText("Version 0.9.0 is available.")).toBeInTheDocument();
    expect(within(notice).getByRole("link", { name: "Release notes" })).toHaveAttribute("href", notes);
    expect(within(notice).getByText("docker compose pull && docker compose up -d")).toBeInTheDocument();
    expect(notice.closest("details")).toBeNull();
  });

  it("dit quand la version servie est la plus récente", async () => {
    mockApi(HEALTH, { tag_name: "v0.7.0", html_url: "https://github.com/jmcruvellier/wattslot/releases/tag/v0.7.0" });

    renderApp();
    await openDiagnostic();

    expect(await screen.findByText("This is the latest version.")).toBeInTheDocument();
  });

  it("change de langue dans les réglages et retient le choix", async () => {
    mockApi(HEALTH);

    renderApp();
    await userEvent.click(await screen.findByRole("link", { name: "Settings" }));
    await userEvent.click(await screen.findByRole("link", { name: /Language and display/ }));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Language" }), "fr");

    const menu = within(screen.getByRole("navigation", { name: "Navigation principale" }));
    expect(menu.getByRole("link", { name: "Réglages" })).toHaveAttribute("aria-current", "page");
    expect(window.localStorage.getItem("wattslot.language")).toBe("fr");
  });

  it("affiche la version de Home Assistant et la dernière erreur, en clair", async () => {
    const health: Health = {
      ...HEALTH,
      connections: {
        home_assistant: {
          state: "error",
          version: "2026.10.1",
          error: "AuthenticationError: jeton refusé",
          error_code: "token_refused",
        },
      },
    };
    mockApi(health);

    renderApp();
    await openDiagnostic();

    expect(await screen.findByText("connection error")).toBeInTheDocument();
    expect(screen.getByText("Home Assistant 2026.10.1")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Last error: Home Assistant refuses the access token: connect the application again (or check the token in the .env file if the connection is set there).",
      ),
    ).toBeInTheDocument();
  });

  it("ouvre le plan du jour dans « Planning »", async () => {
    mockApi(HEALTH);

    renderApp();
    await userEvent.click(await screen.findByRole("link", { name: "Planning" }));

    expect(screen.getByRole("heading", { name: "Today's plan" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Previous dashboard" })).toBeNull(); // supprimé (lot 7.1)
  });

  it("signale une application qui ne répond pas", async () => {
    mockApi(new Response(null, { status: 502 }));

    renderApp();
    await openDiagnostic();

    expect(await screen.findByText(/HTTP 502/)).toHaveAttribute("role", "alert");
  });
});
