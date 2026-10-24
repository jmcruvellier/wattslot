// Discussion avec l'assistant de Home Assistant (page Assistant).

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import ChatCard from "./ChatCard";

const HOME = {
  connected: true,
  mcp: [],
  pipelines: [{ id: "p1", name: "Ollama", conversation_engine: "conversation.ollama" }],
  preferred_pipeline: "p1",
  agents: [
    { id: "conversation.home_assistant", name: "Home Assistant" },
    { id: "conversation.ollama", name: "Ollama" },
  ],
};

type Calls = { url: string; body: Record<string, unknown> }[];

function mockApi(
  chat: (body: Record<string, unknown>) => Response,
  home: unknown = HOME,
  models: unknown = [],
): Calls {
  const calls: Calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    calls.push({ url, body });
    if (url === "api/assistant/home") return Response.json(home);
    if (url === "api/assistant/open-webui/models") return Response.json(models);
    if (url === "api/assistant/chat") return chat(body);
    return new Response(null, { status: 404 });
  });
  return calls;
}

function Harness() {
  const [draft, setDraft] = useState("");
  return <ChatCard inputId="chat" draft={draft} onDraft={setDraft} />;
}

function renderCard() {
  render(
    <I18nProvider>
      <Harness />
    </I18nProvider>,
  );
}

describe("discussion avec l'assistant", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("envoie à l'agent de l'assistant préféré et garde le fil de la conversation", async () => {
    let count = 0;
    const calls = mockApi(() => {
      count += 1;
      return Response.json({ text: `Réponse ${count}`, conversation_id: "c1", error: false });
    });
    renderCard();
    const user = userEvent.setup();

    expect(await screen.findByLabelText("Répondre avec")).toHaveValue("conversation.ollama");
    expect(screen.getByRole("option", { name: "Ollama (assistant préféré)" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Votre message"), "Pourquoi 11 h ?{Enter}");
    expect(await screen.findByText("Réponse 1")).toBeInTheDocument();
    expect(screen.getByText("Pourquoi 11 h ?")).toBeInTheDocument();
    expect(screen.getByLabelText("Votre message")).toHaveValue("");

    await user.type(screen.getByLabelText("Votre message"), "Et demain ?");
    await user.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(await screen.findByText("Réponse 2")).toBeInTheDocument();

    const sent = calls.filter((call) => call.url === "api/assistant/chat").map((call) => call.body);
    expect(sent[0]).toEqual({
      text: "Pourquoi 11 h ?",
      agent_id: "conversation.ollama",
      conversation_id: null,
      language: "fr",
      history: [], // HA garde le fil lui-même
    });
    expect(sent[1].conversation_id).toBe("c1");
  });

  it("garde la conversation quand on quitte la page et qu'on y revient", async () => {
    mockApi(() => Response.json({ text: "Réponse 1", conversation_id: "c1", error: false }));
    const user = userEvent.setup();
    const first = render(
      <I18nProvider>
        <Harness />
      </I18nProvider>,
    );
    await screen.findByLabelText("Répondre avec");
    await user.selectOptions(screen.getByLabelText("Répondre avec"), "conversation.home_assistant");
    await user.type(screen.getByLabelText("Votre message"), "Pourquoi 11 h ?{Enter}");
    expect(await screen.findByText("Réponse 1")).toBeInTheDocument();
    first.unmount(); // une autre page de l'application

    const calls = mockApi(() => Response.json({ text: "Réponse 2", conversation_id: "c1", error: false }));
    renderCard();

    expect(screen.getByText("Pourquoi 11 h ?")).toBeInTheDocument();
    expect(screen.getByText("Réponse 1")).toBeInTheDocument();
    expect(await screen.findByLabelText("Répondre avec")).toHaveValue("conversation.home_assistant");
    await user.type(screen.getByLabelText("Votre message"), "Et demain ?{Enter}");
    expect(await screen.findByText("Réponse 2")).toBeInTheDocument();
    expect(calls.find((call) => call.url === "api/assistant/chat")!.body).toMatchObject({
      conversation_id: "c1",
      agent_id: "conversation.home_assistant",
    });
  });

  it("Maj+Entrée passe à la ligne sans envoyer", async () => {
    const calls = mockApi(() => Response.json({ text: "?", conversation_id: null, error: false }));
    renderCard();
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Votre message"), "Ligne 1{Shift>}{Enter}{/Shift}Ligne 2");

    expect(screen.getByLabelText("Votre message")).toHaveValue("Ligne 1\nLigne 2");
    expect(calls.some((call) => call.url === "api/assistant/chat")).toBe(false);
  });

  it("un autre agent pour tester, puis une nouvelle conversation", async () => {
    const calls = mockApi(() => Response.json({ text: "Bonjour", conversation_id: "c9", error: false }));
    renderCard();
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Répondre avec"), "conversation.home_assistant");
    await user.type(screen.getByLabelText("Votre message"), "Salut{Enter}");
    await screen.findByText("Bonjour");
    await user.click(screen.getByRole("button", { name: "Nouvelle conversation" }));
    await user.type(screen.getByLabelText("Votre message"), "Encore{Enter}");
    await screen.findByText("Bonjour");

    const sent = calls.filter((call) => call.url === "api/assistant/chat").map((call) => call.body);
    expect(sent[0].agent_id).toBe("conversation.home_assistant");
    expect(sent[1].conversation_id).toBeNull();
  });

  it("un modèle d'Open WebUI reçoit l'historique de la conversation", async () => {
    const calls = mockApi(
      () => Response.json({ text: "Réponse", conversation_id: null, error: false }),
      HOME,
      [{ id: "qwen2.5:14b", name: "Qwen" }],
    );
    renderCard();
    const user = userEvent.setup();

    expect(await screen.findByRole("group", { name: "Open WebUI" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Répondre avec"), "open_webui:qwen2.5:14b");
    await user.type(screen.getByLabelText("Votre message"), "Bonjour{Enter}");
    await screen.findByText("Réponse");
    await user.type(screen.getByLabelText("Votre message"), "Et demain ?{Enter}");
    await screen.findAllByText("Réponse");

    const sent = calls.filter((call) => call.url === "api/assistant/chat").map((call) => call.body);
    expect(sent[0]).toMatchObject({ agent_id: "open_webui:qwen2.5:14b", history: [] });
    expect(sent[1].history).toEqual([
      { role: "user", content: "Bonjour" },
      { role: "assistant", content: "Réponse" },
    ]);
  });

  it("sans Home Assistant, Open WebUI reste possible", async () => {
    const calls = mockApi(
      () => Response.json({ text: "Oui", conversation_id: null, error: false }),
      { connected: false, mcp: [], pipelines: [], preferred_pipeline: null, agents: [] },
      [{ id: "qwen2.5:14b", name: "Qwen" }],
    );
    renderCard();
    const user = userEvent.setup();

    expect(await screen.findByLabelText("Répondre avec")).toHaveValue("open_webui:qwen2.5:14b");
    expect(screen.queryByText(/Home Assistant n'est pas connecté/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Votre message"), "Bonjour{Enter}");
    await screen.findByText("Oui");
    expect(calls.find((call) => call.url === "api/assistant/chat")?.body.agent_id).toBe("open_webui:qwen2.5:14b");
  });

  it("affiche le temps mis par une réponse à droite de celle-ci", async () => {
    mockApi(() => Response.json({ text: "Réponse 1", conversation_id: "c1", error: false }));
    renderCard();
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Votre message"), "Pourquoi 11 h ?{Enter}");

    const reply = await screen.findByText("Réponse 1");
    expect(reply.querySelector(".assistant-chat-time")?.textContent).toMatch(/^réponse en \d/);
  });

  it("une erreur s'affiche dans la conversation", async () => {
    mockApi(() => Response.json({ detail: "timeout" }, { status: 502 }));
    renderCard();
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Votre message"), "Bonjour{Enter}");

    expect(await screen.findByText("L'assistant n'a pas répondu, réessayez.")).toBeInTheDocument();
  });

  it("sans Home Assistant : le dit, sans liste d'agents", async () => {
    mockApi(() => Response.json({}, { status: 503 }), {
      connected: false,
      mcp: [],
      pipelines: [],
      preferred_pipeline: null,
      agents: [],
    });
    renderCard();

    expect(await screen.findByText(/Home Assistant n'est pas connecté/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Répondre avec")).not.toBeInTheDocument();
  });
});
