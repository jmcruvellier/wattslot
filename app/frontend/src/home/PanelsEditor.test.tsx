import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import type { SolarPanels } from "./configuration";
import PanelsEditor from "./PanelsEditor";

function Harness({ onChange }: { onChange: (panels: SolarPanels | null) => void }) {
  const [panels, setPanels] = useState<SolarPanels | null>(null);
  return (
    <PanelsEditor
      panels={panels}
      name="Toiture"
      onChange={(next) => {
        setPanels(next);
        onChange(next);
      }}
    />
  );
}

describe("PanelsEditor", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  it("décrit deux champs, l'onduleur et le rendement", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <I18nProvider>
        <Harness onChange={onChange} />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Décrire les panneaux" }));
    await user.click(screen.getByRole("button", { name: "Ajouter un champ" }));
    const second = screen.getByRole("listitem", { name: "Champ 2" });
    const [kwp] = second.querySelectorAll("input");
    fireEvent.change(kwp, { target: { value: "1.6" } });
    await user.selectOptions(second.querySelector("select") as HTMLSelectElement, "90");
    fireEvent.change(screen.getByLabelText("Puissance maximale de l'onduleur"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Rendement (câbles, onduleur, salissures)"), {
      target: { value: "85" },
    });

    expect(onChange).toHaveBeenLastCalledWith({
      arrays: [
        { kwp: 3, tilt: 30, azimuth: 180 },
        { kwp: 1.6, tilt: 30, azimuth: 90 },
      ],
      inverter_kw: 4,
      efficiency: 0.85,
    });

    await user.click(screen.getByRole("button", { name: "Ne plus décrire les panneaux" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("laisse effacer la puissance crête proposée et en taper une autre, avec une virgule", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <I18nProvider>
        <Harness onChange={onChange} />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Décrire les panneaux" }));
    const [kwp] = screen.getByRole("listitem", { name: "Champ 1" }).querySelectorAll("input");
    await user.clear(kwp);
    expect(kwp).toHaveValue("");
    await user.type(kwp, "3,6");
    expect(kwp).toHaveValue("3,6");
    expect(onChange).toHaveBeenLastCalledWith({
      arrays: [{ kwp: 3.6, tilt: 30, azimuth: 180 }],
      inverter_kw: null,
      efficiency: 0.9,
    });
  });
});
