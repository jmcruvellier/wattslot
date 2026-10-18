import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import ForecastComparison, { type Comparison } from "./ForecastComparison";

function renderWith(comparison: Comparison) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json(comparison));
  render(
    <I18nProvider>
      <ForecastComparison />
    </I18nProvider>,
  );
}

describe("ForecastComparison", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("compare la prévision à la production mesurée", async () => {
    renderWith({
      available: true,
      reason: null,
      days: [
        { day: "2026-10-15", forecast_kwh: 10, measured_kwh: 8.5 },
        { day: "2026-10-16", forecast_kwh: 12.25, measured_kwh: null },
      ],
      ratio: 0.85,
    });

    expect(await screen.findByText(/représente 85 % de la prévision/)).toBeTruthy();
    expect(screen.getByText("8,5 kWh")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("dit pourquoi il n'y a rien à comparer", async () => {
    renderWith({ available: false, reason: "no_panels", days: [], ratio: null });

    expect(await screen.findByText(/Aucun panneau décrit/)).toBeTruthy();
  });
});
