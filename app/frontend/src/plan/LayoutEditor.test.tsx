import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { DAY_CARDS, type DashboardLayout, DEFAULT_LAYOUT } from "./layout";
import LayoutEditor from "./LayoutEditor";

function renderEditor(layout: DashboardLayout = DEFAULT_LAYOUT, available = DAY_CARDS.filter((id) => id !== "soc")) {
  const onChange = vi.fn();
  const onReset = vi.fn();
  render(
    <I18nProvider>
      <LayoutEditor
        kind="today"
        layout={layout}
        available={available}
        indicators={["cost_eur", "import_kwh", "export_kwh"]}
        saving={false}
        failed={false}
        onChange={onChange}
        onReset={onReset}
        onClose={vi.fn()}
      />
    </I18nProvider>,
  );
  return { onChange, onReset };
}

describe("panneau « Personnaliser »", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("ne propose que les cartes justifiées par l'installation", () => {
    renderEditor();
    const list = screen.getAllByRole("list")[0];
    expect(within(list).getAllByRole("listitem")).toHaveLength(6);
    expect(within(list).queryByText("Batterie (SoC)")).toBeNull();
    expect(screen.getByRole("button", { name: "Monter « Résumé (SoC, batterie, réseau, production) »" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Revenir à la disposition par défaut" })).toBeDisabled();
  });

  it("descend une carte en sautant celles absentes de l'installation", async () => {
    const user = userEvent.setup();
    const { onChange } = renderEditor();
    await user.click(screen.getByRole("button", { name: "Descendre « Planning des équipements »" }));
    // « soc » (sans batterie) garde sa place : la frise passe après le réseau.
    expect(onChange.mock.calls[0][0].today.order).toEqual([
      "summary",
      "grid",
      "soc",
      "timeline",
      "energy",
      "indicators",
      "explanations",
    ]);
  });

  it("masque puis remet une carte", async () => {
    const user = userEvent.setup();
    const { onChange } = renderEditor();
    await user.click(screen.getByRole("button", { name: "Masquer « Réseau »" }));
    expect(onChange.mock.calls[0][0].today.hidden).toEqual(["grid"]);
  });

  it("liste les cartes masquées avec « Remettre »", async () => {
    const user = userEvent.setup();
    const layout = { ...DEFAULT_LAYOUT, default: false, today: { order: [...DAY_CARDS], hidden: ["grid" as const] } };
    const { onChange, onReset } = renderEditor(layout);
    expect(screen.getByText("Cartes masquées")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remettre « Réseau »" }));
    expect(onChange.mock.calls[0][0].today.hidden).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Revenir à la disposition par défaut" }));
    expect(onReset).toHaveBeenCalled();
  });

  it("choisit l'indicateur mis en avant et masque un indicateur", async () => {
    const user = userEvent.setup();
    const { onChange } = renderEditor();
    await user.selectOptions(screen.getByRole("combobox"), "Achat au réseau");
    expect(onChange.mock.calls[0][0].indicators).toEqual({ highlight: "import_kwh", hidden: [] });
    await user.click(screen.getByRole("checkbox", { name: "Surplus envoyé au réseau" }));
    expect(onChange.mock.calls[1][0].indicators.hidden).toEqual(["export_kwh"]);
  });
});
