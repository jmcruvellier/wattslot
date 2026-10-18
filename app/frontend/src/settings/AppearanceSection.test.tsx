import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
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
});
