// Minutes des plages classiques et par couleur, y compris les anciennes configurations.
import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { TARIFF_TEMPLATES, type Tariff, type TariffKind } from "./configuration";
import TariffEditor from "./TariffEditor";

function Editor({ initial, changed }: { initial: Tariff; changed: (tariff: Tariff | null) => void }) {
  const [tariff, setTariff] = useState<Tariff | null>(initial);
  return <TariffEditor tariff={tariff} onChange={(next) => { setTariff(next); changed(next); }} />;
}

describe("minutes des plages tarifaires", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });
  afterEach(() => vi.restoreAllMocks());

  it.each<TariffKind>(["TimeOfUseTariff", "DayColorTariff"])("garde le legacy, ajoute une plage et règle minuit ou 24:00 : %s", async (kind) => {
    const legacy = { start_hour: 22, end_hour: 6, eur_kwh: 0.1, weekdays: [1], months: [2] };
    const initial = { ...TARIFF_TEMPLATES[kind], bands: [legacy], colors: [{ color: "Bleu", base_eur_kwh: 0.2, bands: [legacy] }] };
    const changed = vi.fn();
    render(<I18nProvider><Editor initial={initial} changed={changed} /></I18nProvider>);
    const name = kind === "DayColorTariff" ? "Bleu · Plage 1" : "Plage 1";
    const band = within(screen.getByRole("listitem", { name }));
    expect(band.getByLabelText("Minutes de début")).toHaveValue("0");
    expect(band.getByLabelText("Minutes de fin")).toHaveValue("0");
    expect(changed).not.toHaveBeenCalled();
    await userEvent.selectOptions(band.getByLabelText("à"), "0");
    await userEvent.selectOptions(band.getByLabelText("Minutes de fin"), "38");
    const latestBand = () => {
      const latest = changed.mock.lastCall![0] as Tariff;
      return kind === "DayColorTariff" ? latest.colors[0].bands[0] : latest.bands[0];
    };
    expect(latestBand()).toMatchObject({ ...legacy, end_hour: 0, end_minute: 38 });
    await userEvent.selectOptions(band.getByLabelText("à"), "24");
    expect(band.getByLabelText("Minutes de fin")).toBeDisabled();
    expect(band.getByLabelText("Minutes de fin")).toHaveValue("0");
    expect(latestBand()).toMatchObject({ end_hour: 24, end_minute: 0 });
    await userEvent.selectOptions(band.getByLabelText("à"), "0");
    expect(band.getByLabelText("Minutes de fin")).toBeEnabled();
    expect(band.getByLabelText("Minutes de fin")).toHaveValue("0");
    await userEvent.click(screen.getByRole("button", { name: "Ajouter une plage" }));
    const latest = changed.mock.lastCall![0] as Tariff;
    const added = (kind === "DayColorTariff" ? latest.colors[0].bands : latest.bands)[1];
    expect(added).toMatchObject({ start_hour: 0, start_minute: 0, end_hour: 6, end_minute: 0 });
  });
});
