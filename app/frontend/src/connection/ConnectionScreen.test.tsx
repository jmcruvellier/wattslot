import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { applicationAddress, returnedFromHomeAssistant } from "./address";
import ConnectionScreen, { type ConnectionInfo } from "./ConnectionScreen";

const NONE: ConnectionInfo = {
  mode: "standalone",
  source: null,
  url: null,
  method: null,
  state: "not_configured",
  error: null,
};

type Call = { url: string; method: string; body: unknown };

function mockApi(info: ConnectionInfo, answers: Record<string, Response> = {}): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url === "api/connection" && method === "GET") return Response.json(info);
    return answers[`${method} ${url}`] ?? Response.json({});
  });
  return calls;
}

const original = window.location;
let assign: ReturnType<typeof vi.fn>;

function renderScreen(returned: string | null = null) {
  render(
    <I18nProvider>
      <ConnectionScreen returned={returned} />
    </I18nProvider>,
  );
}

describe("ConnectionScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
    assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { origin: "http://192.0.2.10:8100", pathname: "/", search: "", assign },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, "location", { configurable: true, value: original });
  });

  it("ouvre la page de connexion de Home Assistant", async () => {
    const user = userEvent.setup();
    const calls = mockApi(NONE, {
      "POST api/connection/oauth": Response.json({ authorize_url: "http://ha:8123/auth/authorize?x=1" }),
    });
    renderScreen();

    await user.type(await screen.findByLabelText("Adresse de Home Assistant"), "http://ha:8123");
    await user.click(screen.getByRole("button", { name: "Se connecter avec Home Assistant" }));

    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      url: "http://ha:8123",
      client_id: "http://192.0.2.10:8100",
    });
    expect(assign).toHaveBeenCalledWith("http://ha:8123/auth/authorize?x=1");
  });

  it("dit pourquoi un jeton est refusé", async () => {
    const user = userEvent.setup();
    mockApi(NONE, {
      "POST api/connection/token": Response.json({ detail: "token_refused" }, { status: 400 }),
    });
    renderScreen();

    await user.type(await screen.findByLabelText("Adresse de Home Assistant"), "http://ha:8123");
    await user.type(screen.getByLabelText("Jeton"), "abc");
    await user.click(screen.getByRole("button", { name: "Se connecter avec ce jeton" }));

    expect(await screen.findByText("Home Assistant a refusé ce jeton.")).toBeInTheDocument();
  });

  it("se déconnecte et attend le redémarrage", async () => {
    const user = userEvent.setup();
    const calls = mockApi({ ...NONE, source: "saved", url: "http://ha:8123", method: "oauth", state: "connected" });
    renderScreen("ok");

    expect(await screen.findByText(/Connexion acceptée par Home Assistant/)).toBeInTheDocument();
    expect(screen.getByText("Connectée à http://ha:8123 avec votre compte Home Assistant.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));

    expect(calls.some((call) => call.url === "api/connection" && call.method === "DELETE")).toBe(true);
    expect(await screen.findByText(/L'application redémarre/)).toBeInTheDocument();
  });

  it("ne propose rien quand l'environnement fixe la connexion", async () => {
    mockApi({ ...NONE, source: "env", state: "connected" });
    renderScreen();

    expect(await screen.findByText(/fixée par les variables d'environnement/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Se connecter avec Home Assistant" })).not.toBeInTheDocument();
  });
});

describe("adresses", () => {
  it("adresse de l'application et retour de Home Assistant", () => {
    const location = { origin: "http://h:8100", pathname: "/app/" } as Location;
    expect(applicationAddress(location)).toBe("http://h:8100/app");
    expect(returnedFromHomeAssistant("?connection=ok")).toBe("ok");
    expect(returnedFromHomeAssistant("")).toBeNull();
  });
});
