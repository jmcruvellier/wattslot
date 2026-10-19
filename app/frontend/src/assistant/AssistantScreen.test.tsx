import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { LANGUAGES } from "../i18n/translate";
import AssistantScreen from "./AssistantScreen";

const PROMPT = "Tu es l'assistant énergie d'une maison avec des panneaux solaires.";

function mockApi({ addon = false, mcp = true }: { addon?: boolean; mcp?: boolean } = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/assistant/connection") {
      return Response.json(
        addon
          ? { mode: "addon", mcp_url: "http://a0d7b954-wattslot:8100/mcp" }
          : { mode: "standalone", mcp_url: null },
      );
    }
    if (url.startsWith("api/assistant/prompt")) return Response.json({ language: "fr", prompt: PROMPT });
    if (url === "mcp" && mcp) {
      const body = JSON.parse(String(init?.body)) as { id: number; method: string };
      const result = body.method === "tools/list" ? { tools: new Array(9).fill({ name: "x" }) } : { serverInfo: {} };
      return Response.json({ jsonrpc: "2.0", id: body.id, result });
    }
    return new Response(null, { status: 503 });
  });
}

function renderScreen() {
  render(
    <I18nProvider>
      <AssistantScreen />
    </I18nProvider>,
  );
}

describe("page « Assistant »", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("mode autonome : l'adresse du navigateur, suivie de /mcp, et le prompt à copier", async () => {
    mockApi();
    renderScreen();

    expect(await screen.findByText(PROMPT)).toBeInTheDocument();
    expect(screen.getByText(`${window.location.origin}/mcp`)).toBeInTheDocument();
    expect(screen.getByText(/ne l'ouvrez pas sur Internet/)).toBeInTheDocument();
    expect(screen.getByLabelText("Copier le prompt")).toBeInTheDocument(); // replié : pas de rôle accessible
  });

  it("extension : l'adresse sur le réseau interne de Home Assistant", async () => {
    mockApi({ addon: true });
    renderScreen();

    expect(await screen.findByText("http://a0d7b954-wattslot:8100/mcp")).toBeInTheDocument();
    expect(screen.getByText(/réseau interne de Home Assistant/)).toBeInTheDocument();
  });

  it("copie l'adresse dans le presse-papiers", async () => {
    const user = userEvent.setup();
    mockApi({ addon: true });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderScreen();

    await screen.findByText("Le serveur MCP répond : 9 outils.");
    await user.click(screen.getByText("Brancher l'Assist pas à pas")); // replié une fois vérifié
    await user.click(screen.getByRole("button", { name: "Copier l'adresse du serveur MCP" }));
    expect(writeText).toHaveBeenCalledWith("http://a0d7b954-wattslot:8100/mcp");
    expect(await screen.findByText("Copié")).toBeInTheDocument();
  });

  it("vérifie le serveur MCP à l'ouverture, puis sur demande, et replie le branchement", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi();
    renderScreen();

    expect(await screen.findByText("Le serveur MCP répond : 9 outils.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prêt pour l'Assist de Home Assistant" })).toBeInTheDocument();
    const setup = screen.getByText("Brancher l'Assist pas à pas").closest("details") as HTMLDetailsElement;
    expect(setup.open).toBe(false);
    const methods = () =>
      fetchMock.mock.calls
        .filter(([url]) => String(url) === "mcp")
        .map(([, init]) => (JSON.parse(String(init?.body)) as { method: string }).method);
    expect(methods()).toEqual(["initialize", "tools/list"]);

    await user.click(screen.getByRole("button", { name: "Vérifier" }));
    await screen.findByText("Le serveur MCP répond : 9 outils.");
    expect(methods()).toEqual(["initialize", "tools/list", "initialize", "tools/list"]);
  });

  it("dit quand le serveur MCP ne répond pas, branchement déplié", async () => {
    mockApi({ mcp: false });
    renderScreen();

    expect(await screen.findByText("Le serveur MCP ne répond pas (HTTP 503).")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Le serveur de l'assistant ne répond pas" })).toBeInTheDocument();
    expect((screen.getByText("Brancher l'Assist pas à pas").closest("details") as HTMLDetailsElement).open).toBe(true);
  });

  it("une question d'exemple remplit la zone de saisie du chat, sans ses guillemets", async () => {
    mockApi();
    renderScreen();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "« Combien les panneaux ont-ils produit hier ? »" }));

    const input = screen.getByLabelText("Votre message");
    expect(input).toHaveValue("Combien les panneaux ont-ils produit hier ?");
    expect(input).toHaveFocus();
  });

  it.each(LANGUAGES)("%s : aucune clé brute", async (language) => {
    window.localStorage.setItem("wattslot.language", language);
    mockApi();
    renderScreen();
    await screen.findByText(PROMPT);
    // Le catalogue chargé à la demande est lu : plus de texte de secours en anglais à attendre.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.body.textContent ?? "").not.toMatch(/\bassistant\.[a-z_.]+/);
  });
});
