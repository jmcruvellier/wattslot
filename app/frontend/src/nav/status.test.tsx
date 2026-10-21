// Pastille d'état et feuille « Demander un appareil » (lot 6b.2).

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type { Problem } from "../diagnostic/ProblemsSection";
import { I18nProvider } from "../i18n/I18nProvider";
import { statusLevel } from "./status";

function problem(severity: Problem["severity"]): Problem {
  return { code: "x", severity, params: {}, target: null, doc: null };
}

describe("niveau de la pastille", () => {
  it("prend le problème le plus grave, sans compter « à surveiller »", () => {
    expect(statusLevel([])).toBe("ok");
    expect(statusLevel([problem("watch")])).toBe("ok");
    expect(statusLevel([problem("watch"), problem("degraded")])).toBe("degraded");
    expect(statusLevel([problem("degraded"), problem("blocking")])).toBe("blocking");
  });

  it("dit « Mise en route » quand seules les étapes avant le premier plan bloquent", () => {
    const setup = { ...problem("blocking"), setup: true };
    expect(statusLevel([setup, problem("degraded")])).toBe("setup");
    expect(statusLevel([setup, problem("blocking")])).toBe("blocking");
  });
});

interface Api {
  problems?: Problem[] | null;
  devices?: { key: string; name: string }[];
}

function mockApi({ problems = [], devices = [{ key: "dishwasher", name: "Lave-vaisselle" }] }: Api) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/diagnostic/problems") {
      return problems === null ? new Response(null, { status: 500 }) : Response.json(problems);
    }
    if (url === "api/requests/devices") return Response.json(devices);
    if (url === "api/requests" && init?.method === "POST") return Response.json({ id: 1 });
    if (url === "api/setup") return Response.json({ ready: false, steps: [] });
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

describe("barre de l'application", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = "";
  });

  it("affiche « Tout fonctionne » et mène à l'état de l'application", async () => {
    mockApi({ problems: [problem("watch")] });
    renderApp();
    const pills = await screen.findAllByRole("link", { name: "Tout fonctionne" });
    expect(pills[0]).toHaveAttribute("href", "#/settings/status");
  });

  it("passe à l'orange puis au rouge selon les problèmes", async () => {
    mockApi({ problems: [problem("degraded")] });
    const { unmount } = renderApp();
    expect((await screen.findAllByRole("link", { name: "À vérifier" }))[0]).toHaveAttribute("data-level", "degraded");
    unmount();

    vi.restoreAllMocks();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    mockApi({ problems: [problem("blocking")] });
    renderApp();
    expect(await screen.findAllByRole("link", { name: "Le calcul est bloqué" })).not.toHaveLength(0);
  });

  it("ne montre pas de pastille quand le serveur ne répond pas", async () => {
    const fetch = mockApi({ problems: null });
    renderApp();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("api/diagnostic/problems", expect.anything()));
    expect(screen.queryByRole("link", { name: /fonctionne|vérifier|bloqué/ })).not.toBeInTheDocument();
  });

  it("dépose une demande depuis la feuille et confirme", async () => {
    const fetch = mockApi({});
    renderApp();
    await userEvent.click(screen.getAllByRole("button", { name: "Demander un appareil" })[0]);
    const sheet = await screen.findByRole("dialog", { name: "Demander un appareil" });
    await userEvent.click(await within(sheet).findByRole("button", { name: "Demander" }));

    expect(await within(sheet).findByRole("status")).toHaveTextContent("Demande enregistrée");
    const post = fetch.mock.calls.find(([url, init]) => url === "api/requests" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ device: "dishwasher", latest: null });

    await userEvent.click(within(sheet).getByRole("button", { name: "Terminé" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("dit quand aucun appareil ne se lance à la demande", async () => {
    mockApi({ devices: [] });
    renderApp();
    await userEvent.click(screen.getAllByRole("button", { name: "Demander un appareil" })[0]);
    expect(await screen.findByText(/Aucun appareil de votre maison/)).toBeInTheDocument();
  });
});
