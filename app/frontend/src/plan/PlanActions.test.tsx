import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import PlanActions from "./PlanActions";

function lastRun(computedMinutesAgo: number | null, readMinutesAgo: number | null, manual = false) {
  return {
    computed_at: computedMinutesAgo === null ? null : new Date(Date.now() - computedMinutesAgo * 60_000).toISOString(),
    manual,
    actual_updated_at: readMinutesAgo === null ? null : new Date(Date.now() - readMinutesAgo * 60_000).toISOString(),
  };
}

/** Réponses de l'API ; `run` dit si « Calculer » et « Rafraîchir » réussissent. */
function mockApi(last: ReturnType<typeof lastRun>, run: "ok" | "fail" = "ok") {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "api/planning/last-run") return Response.json(last);
    if (init?.method === "POST") {
      if (run === "fail") return Response.json({ detail: "erreur" }, { status: 500 });
      return Response.json({});
    }
    return Response.json({ detail: "inattendu" }, { status: 404 });
  });
}

function renderActions() {
  return render(
    <I18nProvider>
      <PlanActions />
    </I18nProvider>,
  );
}

describe("PlanActions (barre de titre)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("montre l'âge du dernier calcul et du dernier relevé à côté des icônes", async () => {
    mockApi(lastRun(12, 5));

    renderActions();

    expect(await screen.findByText("il y a 12 minutes")).toBeInTheDocument();
    expect(screen.getByText("il y a 5 minutes")).toBeInTheDocument();
    // Le détail (heure, automatique ou à la main) est dans le nom du bouton.
    expect(await screen.findByRole("button", { name: /^Calculer — Calculé à .+ \(automatique\)$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Rafraîchir les données réelles — dernier relevé à .+$/ })).toBeInTheDocument();
  });

  it("jamais calculé ni relevé : tirets, et le détail le dit au lecteur d'écran", async () => {
    mockApi(lastRun(null, null));

    renderActions();

    expect(await screen.findByRole("button", { name: "Calculer — Jamais calculé" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rafraîchir les données réelles" })).toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("« Calculer » lance un calcul puis relit la dernière exécution", async () => {
    const fetchMock = mockApi(lastRun(12, 5));
    renderActions();
    await screen.findByText("il y a 12 minutes");
    const reads = () => fetchMock.mock.calls.filter(([url]) => String(url) === "api/planning/last-run").length;
    const before = reads();

    await userEvent.click(screen.getByRole("button", { name: /^Calculer/ }));

    expect(fetchMock).toHaveBeenCalledWith("api/planning/run", { method: "POST" });
    await waitFor(() => expect(reads()).toBe(before + 1));
  });

  it("« Rafraîchir les données réelles » relit les mesures du jour", async () => {
    const fetchMock = mockApi(lastRun(12, 5));
    renderActions();

    await userEvent.click(await screen.findByRole("button", { name: /^Rafraîchir/ }));

    expect(fetchMock).toHaveBeenCalledWith("api/planning/actual", { method: "POST" });
  });

  it("« Rafraîchir » : seul ce bouton s'anime, « Calculer » garde son âge affiché", async () => {
    let release: ((response: Response) => void) | undefined;
    const done = new Promise<Response>((resolve) => {
      release = resolve;
    });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "api/planning/last-run") return Response.json(lastRun(12, 5));
      if (init?.method === "POST") return done;
      return Response.json({ detail: "inattendu" }, { status: 404 });
    });
    renderActions();
    const compute = await screen.findByRole("button", { name: /^Calculer/ });

    await userEvent.click(screen.getByRole("button", { name: /^Rafraîchir/ }));

    // Calculer : désactivé (un calcul à la fois) mais pas animé, son âge n'a pas bougé.
    expect(compute).toBeDisabled();
    expect(compute).not.toHaveClass("run-button-running");
    expect(screen.getByText("il y a 12 minutes")).toBeInTheDocument();
    const refresh = screen.getByRole("button", { name: /^Rafraîchir/ });
    expect(refresh).toBeDisabled();
    expect(refresh).toHaveClass("run-button-running");

    await act(async () => {
      release!(Response.json({}));
    });
    expect(screen.getByRole("button", { name: /^Rafraîchir/ })).toBeEnabled();
  });

  it("échec : un message d'alerte, les boutons restent utilisables", async () => {
    mockApi(lastRun(12, 5), "fail");
    renderActions();

    await userEvent.click(await screen.findByRole("button", { name: /^Calculer/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("L'opération a échoué : voir le diagnostic.");
    expect(screen.getByRole("button", { name: /^Rafraîchir/ })).toBeEnabled();
  });
});
