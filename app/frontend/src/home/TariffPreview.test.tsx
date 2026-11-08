// Aperçu des prix d'un tarif : lignes, cases, légende, survol, jour férié et sortes de jours.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { TARIFF_TEMPLATES } from "./configuration";
import TariffPreview from "./TariffPreview";

const flat = (price: number) => Array.from({ length: 24 }, () => price);
const offPeak = Array.from({ length: 24 }, (_, hour) => (hour < 6 ? 0.15 : 0.25));

function answer(rows: unknown[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ rows }));
}

describe("aperçu des prix", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });
  afterEach(() => vi.restoreAllMocks());

  it("montre les sept jours, les jours fériés, la légende et le prix survolé", async () => {
    const fetch = answer([
      { day: "2026-11-10", holiday: false, color: null, prices: offPeak },
      { day: "2026-11-11", holiday: true, color: null, prices: flat(0.15) },
    ]);
    render(<I18nProvider><TariffPreview tariff={TARIFF_TEMPLATES.TimeOfUseTariff} /></I18nProvider>);
    const grid = await screen.findByRole("table");
    expect(fetch).toHaveBeenCalledWith("api/configuration/tariff-preview", expect.objectContaining({ method: "POST" }));
    expect(screen.getByText("Aperçu des 7 prochains jours")).toBeInTheDocument();
    const rows = within(grid).getAllByRole("row");
    expect(rows).toHaveLength(3); // heures, puis deux jours
    expect(within(rows[2]).getByRole("rowheader")).toHaveTextContent("mer. 11 (férié)");
    const cells = within(rows[1]).getAllByRole("cell");
    expect(cells).toHaveLength(24);
    expect(cells[3]).toHaveAccessibleName("3 h – 4 h : 0,15 €/kWh");
    const legend = within(screen.getByRole("list", { name: "Prix du kWh" })).getAllByRole("listitem");
    expect(legend.map((item) => item.textContent?.trim())).toEqual(["0,15 €/kWh", "0,25 €/kWh"]);
    await userEvent.hover(cells[12]);
    expect(document.querySelector(".tariff-preview-readout")?.textContent).toBe("mar. 10 · 12 h – 13 h : 0,25 €/kWh");
  });

  it("montre une ligne par sorte de jour annoncé", async () => {
    answer([
      { day: "2026-11-10", holiday: false, color: "Normal", prices: flat(0.2) },
      { day: "2026-11-10", holiday: false, color: "EJP", prices: flat(0.9) },
    ]);
    render(<I18nProvider><TariffPreview tariff={TARIFF_TEMPLATES.DayColorTariff} /></I18nProvider>);
    await screen.findByRole("table");
    expect(screen.getByText("Aperçu de chaque sorte de jour")).toBeInTheDocument();
    expect(screen.getAllByRole("rowheader").map((header) => header.textContent)).toEqual(["Jour Normal", "Jour EJP"]);
  });

  it("le dit quand l'aperçu échoue", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("", { status: 500 }));
    render(<I18nProvider><TariffPreview tariff={TARIFF_TEMPLATES.TimeOfUseTariff} /></I18nProvider>);
    expect(await screen.findByText("L'aperçu des prix n'a pas pu être calculé.")).toBeInTheDocument();
  });
});
