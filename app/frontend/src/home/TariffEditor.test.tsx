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

  it.each<TariffKind>(["TimeOfUseTariff", "DayColorTariff"])("garde le legacy, règle les minutes et 24:00, ajoute une plage : %s", async (kind) => {
    const legacy = { start_hour: 22, end_hour: 6, eur_kwh: 0.1, weekdays: [1], months: [2] };
    const initial = { ...TARIFF_TEMPLATES[kind], bands: [legacy], colors: [{ color: "Bleu", base_eur_kwh: 0.2, bands: [legacy] }] };
    const changed = vi.fn();
    render(<I18nProvider><Editor initial={initial} changed={changed} /></I18nProvider>);
    const name = kind === "DayColorTariff" ? "Bleu · Plage 1" : "Plage 1";
    const band = within(screen.getByRole("listitem", { name }));
    expect(band.getByLabelText("Minutes de début")).toHaveValue("0");
    expect(band.getByLabelText("Minutes de fin")).toHaveValue("0");
    expect(screen.queryByText("Minutes de début")).toBeNull(); // la minute suit l'heure, sans texte visible
    expect(changed).not.toHaveBeenCalled();
    await userEvent.selectOptions(band.getByLabelText("Minutes de début"), "30");
    await userEvent.selectOptions(band.getByLabelText("à"), "2");
    await userEvent.selectOptions(band.getByLabelText("Minutes de fin"), "38");
    const latestBand = () => {
      const latest = changed.mock.lastCall![0] as Tariff;
      return kind === "DayColorTariff" ? latest.colors[0].bands[0] : latest.bands[0];
    };
    expect(latestBand()).toMatchObject({ ...legacy, start_minute: 30, end_hour: 2, end_minute: 38 });
    await userEvent.selectOptions(band.getByLabelText("à"), "24");
    expect(band.getByLabelText("Minutes de fin")).toBeDisabled();
    expect(band.getByLabelText("Minutes de fin")).toHaveValue("0");
    expect(latestBand()).toMatchObject({ end_hour: 24, end_minute: 0 });
    await userEvent.selectOptions(band.getByLabelText("à"), "6");
    expect(band.getByLabelText("Minutes de fin")).toBeEnabled();
    expect(band.getByLabelText("Minutes de fin")).toHaveValue("0");
    await userEvent.click(screen.getByRole("button", { name: "Ajouter une plage" }));
    const latest = changed.mock.lastCall![0] as Tariff;
    const added = (kind === "DayColorTariff" ? latest.colors[0].bands : latest.bands)[1];
    expect(added).toMatchObject({ start_hour: 0, start_minute: 0, end_hour: 6, end_minute: 0 });
  });

  it("lit un prix dans Home Assistant, garde le prix saisi en repli, puis revient à la saisie", async () => {
    const changed = vi.fn();
    render(<I18nProvider><Editor initial={TARIFF_TEMPLATES.TimeOfUseTariff} changed={changed} /></I18nProvider>);
    expect(screen.queryByLabelText("Unité des prix lus dans Home Assistant")).toBeNull();
    const band = within(screen.getByRole("listitem", { name: "Plage 1" }));
    await userEvent.click(band.getByRole("button", { name: "lire dans Home Assistant" }));
    await userEvent.type(band.getByLabelText("capteur"), "sensor.tarif_heures_creuses_ttc");
    const latest = () => changed.mock.lastCall![0] as Tariff;
    expect(latest().bands[0]).toMatchObject({ eur_kwh: 0.15, eur_kwh_entity: "sensor.tarif_heures_creuses_ttc" });
    expect(band.getByText(/si le capteur est indisponible/)).toBeInTheDocument();
    expect(screen.getByLabelText("Unité des prix lus dans Home Assistant")).toBeInTheDocument();
    const base = screen.getByLabelText(/Prix hors des plages/).closest("p")!;
    await userEvent.click(within(base).getByRole("button", { name: "lire dans Home Assistant" }));
    await userEvent.type(within(base).getByLabelText("capteur"), "sensor.hp");
    expect(latest().base_eur_kwh_entity).toBe("sensor.hp");
    await userEvent.click(band.getByRole("button", { name: "saisir le prix" }));
    expect(latest().bands[0].eur_kwh_entity).toBeNull();
    expect(band.getByRole("button", { name: "lire dans Home Assistant" })).toBeInTheDocument();
  });
});
