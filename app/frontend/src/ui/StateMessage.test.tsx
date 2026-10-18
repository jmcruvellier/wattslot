// États d'un écran (lot 6b.7).

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { TODAY } from "../plan/testViews";
import TodayView from "../today/TodayView";
import StateMessage from "./StateMessage";

function renderFr(node: React.ReactNode) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

describe("StateMessage", () => {
  beforeEach(() => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("annonce le chargement poliment, une erreur tout de suite avec un conseil", async () => {
    const onRetry = vi.fn();
    const { unmount } = renderFr(<StateMessage kind="loading" title="Lecture…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Lecture…");
    unmount();

    renderFr(<StateMessage kind="error" title="Impossible de lire le plan." onRetry={onRetry} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Impossible de lire le plan.");
    expect(alert).toHaveTextContent("Vérifiez que l'application et Home Assistant sont démarrés");
    await userEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("rien à afficher : un message sans conseil d'erreur", () => {
    renderFr(<StateMessage kind="empty" title="Pas encore de plan." />);
    expect(screen.getByRole("status")).toHaveTextContent("Pas encore de plan.");
    expect(screen.queryByText(/Vérifiez/)).toBeNull();
  });

  it("« Réessayer » relit l'écran Aujourd'hui", async () => {
    let failing = true;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      failing ? new Response(null, { status: 502 }) : Response.json(TODAY),
    );
    renderFr(<TodayView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Impossible de lire le plan du jour.");
    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByText("En ce moment")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
