import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CurrencyProvider } from "../i18n/currency";
import { I18nProvider } from "../i18n/I18nProvider";
import type { CurrencyState } from "../i18n/money";
import { THEME_STORAGE_KEY } from "../theme/theme";
import AppearanceSection from "./AppearanceSection";

function renderSection() {
  return render(
    <I18nProvider>
      <AppearanceSection />
    </I18nProvider>,
  );
}

describe("AppearanceSection", () => {
  beforeEach(() => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("propose Automatique par défaut", () => {
    renderSection();
    expect(screen.getByRole("radio", { name: /Automatique/ })).toBeChecked();
  });

  it("applique et garde le thème choisi", async () => {
    renderSection();
    await userEvent.click(screen.getByRole("radio", { name: /Crépuscule/ }));
    expect(document.documentElement.dataset.theme).toBe("dusk");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dusk");

    await userEvent.click(screen.getByRole("radio", { name: /Automatique/ }));
    expect(document.documentElement.dataset.theme).toBe("auto");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it("reprend le thème gardé, et ignore une valeur inconnue", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "ocean");
    const { unmount } = renderSection();
    expect(screen.getByRole("radio", { name: /Océan/ })).toBeChecked();
    unmount();

    window.localStorage.setItem(THEME_STORAGE_KEY, "rose");
    renderSection();
    expect(screen.getByRole("radio", { name: /Automatique/ })).toBeChecked();
  });

  it("règle la devise de la maison, Home Assistant par défaut", async () => {
    let state: CurrencyState = { code: null, home_assistant: "SEK", effective: "SEK", choices: ["EUR", "CHF", "SEK"] };
    const sent: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as { code: string | null };
        sent.push(body);
        state = { ...state, code: body.code, effective: body.code ?? "SEK" };
      }
      return Response.json(state);
    });
    render(
      <I18nProvider>
        <CurrencyProvider>
          <AppearanceSection />
        </CurrencyProvider>
      </I18nProvider>,
    );

    const select = await screen.findByRole("combobox", { name: "Devise" });
    expect(select).toHaveDisplayValue(/Automatique : couronne suédoise \(Home Assistant\)/);
    expect(screen.getByText(/ne convertit pas les prix déjà saisis/)).toBeInTheDocument();
    await userEvent.selectOptions(select, "CHF");
    expect(sent).toEqual([{ code: "CHF" }]);
    expect(await screen.findByRole("combobox", { name: "Devise" })).toHaveValue("CHF");
  });
});
