// Bloc « Open WebUI » de la sous-page « Assistant vocal ».

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import OpenWebUISettings from "./OpenWebUISettings";

type Calls = { url: string; method: string; body: Record<string, unknown> | null }[];

function mockApi(saved: { url: string | null; has_key: boolean }, test: () => Response): Calls {
  const calls: Calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ url, method, body });
    if (url === "api/assistant/open-webui" && method === "PUT") {
      const kept = body?.clear_key ? false : Boolean(body?.api_key) || saved.has_key;
      return Response.json({ url: body?.url ?? null, has_key: kept });
    }
    if (url === "api/assistant/open-webui") return Response.json(saved);
    if (url === "api/assistant/open-webui/test") return test();
    return new Response(null, { status: 404 });
  });
  return calls;
}

function renderBlock(mode: "addon" | "standalone" = "standalone") {
  render(
    <I18nProvider>
      <OpenWebUISettings mode={mode} />
    </I18nProvider>,
  );
}

describe("bloc « Open WebUI »", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("teste puis enregistre l'adresse et la clé, sans jamais réafficher la clé", async () => {
    const calls = mockApi({ url: null, has_key: false }, () => Response.json([{ id: "a" }, { id: "b" }]));
    renderBlock();
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Adresse"), "http://192.0.2.10:3000");
    await user.type(screen.getByLabelText("Clé d'API"), "secret");
    await user.click(screen.getByRole("button", { name: "Tester" }));
    expect(await screen.findByText("Open WebUI répond : 2 modèle(s).")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText(/clé enregistrée/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Clé d'API")).not.toBeInTheDocument();
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({
      url: "http://192.0.2.10:3000",
      api_key: "secret",
    });
  });

  it("une clé enregistrée se garde, se remplace ou s'efface", async () => {
    const calls = mockApi({ url: "http://192.0.2.10:3000", has_key: true }, () => Response.json([]));
    renderBlock();
    const user = userEvent.setup();

    expect(await screen.findByLabelText("Adresse")).toHaveValue("http://192.0.2.10:3000");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    await screen.findByText("Réglages enregistrés.");
    expect(calls.filter((call) => call.method === "PUT")[0].body).toEqual({ url: "http://192.0.2.10:3000", api_key: null });

    await user.click(screen.getByRole("button", { name: "Remplacer" }));
    expect(screen.getByLabelText("Clé d'API")).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    await user.click(await screen.findByRole("button", { name: "Effacer" }));
    expect(await screen.findByLabelText("Clé d'API")).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "PUT").at(-1)?.body).toMatchObject({ clear_key: true });
  });

  it("dit pourquoi Open WebUI ne répond pas", async () => {
    mockApi({ url: "http://192.0.2.10:3000", has_key: true }, () => Response.json({ detail: "HTTP 401" }, { status: 502 }));
    renderBlock();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Tester" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Open WebUI ne répond pas (HTTP 401).");
  });

  it("en extension, prévient que le serveur MCP est hors de portée d'Open WebUI", async () => {
    mockApi({ url: null, has_key: false }, () => Response.json([]));
    renderBlock("addon");

    expect(await screen.findByText(/n'est joignable que par Home Assistant/)).toBeInTheDocument();
  });
});
