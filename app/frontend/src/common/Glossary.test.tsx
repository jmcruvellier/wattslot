import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import Glossary from "./Glossary";

describe("Glossary", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  it("explique les mots de l'énergie, replié", () => {
    const { container } = render(
      <I18nProvider>
        <Glossary />
      </I18nProvider>,
    );

    expect(container.querySelector("details")?.open).toBe(false);
    expect(screen.getByText("Lexique")).toBeInTheDocument();
    expect(screen.getByText("Surplus envoyé au réseau")).toBeInTheDocument();
    expect(screen.getByText("Les heures où votre contrat facture le kWh moins cher.")).toBeInTheDocument();
    expect(container.querySelectorAll("dt")).toHaveLength(11);
  });
});
