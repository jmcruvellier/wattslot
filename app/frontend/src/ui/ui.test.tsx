// Composants de base (lot 6b.1) : rôles, clavier, focus de la feuille, démonstration dans chaque
// thème, et aucune couleur écrite en dur dans les composants de l'interface.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import Button from "./Button";
import Card from "./Card";
import SettingRow, { SettingList } from "./SettingRow";
import Sheet from "./Sheet";
import Switch from "./Switch";
import UiGallery from "./UiGallery";

function renderFr(node: React.ReactNode) {
  return render(<I18nProvider>{node}</I18nProvider>);
}

beforeEach(() => {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
});

describe("Switch", () => {
  function Controlled() {
    const [on, setOn] = useState(false);
    return <Switch label="Animations" description="Réduites" checked={on} onChange={setOn} />;
  }

  it("porte son libellé et bascule au clic comme au clavier", async () => {
    render(<Controlled />);
    const toggle = screen.getByRole("switch", { name: "Animations" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toHaveAccessibleDescription("Réduites");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    toggle.focus();
    await userEvent.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });
});

describe("Sheet", () => {
  function Opener() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Ouvrir
        </button>
        <Sheet open={open} title="Demander un appareil" onClose={() => setOpen(false)}>
          <input aria-label="Appareil" />
          <button type="button">Valider</button>
        </Sheet>
      </>
    );
  }

  it("prend le focus, le garde au clavier, se ferme par Échap et le rend", async () => {
    renderFr(<Opener />);
    const opener = screen.getByRole("button", { name: "Ouvrir" });
    await userEvent.click(opener);
    expect(screen.getByRole("dialog", { name: "Demander un appareil" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Appareil" })).toHaveFocus();

    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Valider" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Fermer" })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Valider" })).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("se ferme par son bouton ou par un clic à côté", async () => {
    renderFr(<Opener />);
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    await userEvent.click(screen.getByRole("button", { name: "Fermer" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    await userEvent.click(screen.getByRole("dialog").parentElement as HTMLElement);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Card, Button, SettingRow", () => {
  it("nomme la carte par son titre et range les boutons par variante", () => {
    render(
      <Card eyebrow="En ce moment" title="Le soleil couvre 82 % de la maison">
        <Button variant="primary" icon="check">
          C'est lancé
        </Button>
      </Card>,
    );
    expect(screen.getByRole("region", { name: "Le soleil couvre 82 % de la maison" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "C'est lancé" })).toHaveClass("ui-button-primary");
  });

  it("fait d'une ligne qui ouvre un écran un bouton", async () => {
    const onOpen = vi.fn();
    render(
      <SettingList>
        <SettingRow label="Notifications" description="2 actives" onOpen={onOpen} />
        <SettingRow label="Unités">kW</SettingRow>
      </SettingList>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));
    expect(onOpen).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /Unités/ })).not.toBeInTheDocument();
  });
});

describe("UiGallery", () => {
  it("montre les composants dans chacun des cinq thèmes", () => {
    renderFr(<UiGallery />);
    for (const [name, theme] of [
      ["Ivoire", "ivory"],
      ["Graphite", "graphite"],
      ["Océan", "ocean"],
      ["Prairie", "meadow"],
      ["Crépuscule", "dusk"],
    ]) {
      const panel = screen.getByRole("region", { name });
      expect(panel).toHaveAttribute("data-theme", theme);
    }
    expect(screen.getAllByRole("switch")).toHaveLength(5);
  });
});

describe("couleurs", () => {
  it("n'écrit aucune couleur en dur dans les composants : elles viennent du thème", () => {
    const sources = import.meta.glob<string>(["../**/*.tsx", "!../**/*.test.tsx"], {
      query: "?raw",
      import: "default",
      eager: true,
    });
    expect(Object.keys(sources).length).toBeGreaterThan(20);
    for (const [file, source] of Object.entries(sources)) {
      // Un « # » collé à un mot est une ancre (« devices#add-device »), pas une couleur.
      expect(source.match(/(?<![\w-])#[0-9a-fA-F]{3,8}\b|rgba?\(/g), file).toBeNull();
    }
  });
});
