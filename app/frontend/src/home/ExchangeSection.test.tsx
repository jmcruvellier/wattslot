import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import ExchangeSection from "./ExchangeSection";

const FILE = { format: "wattslot/home", version: 1, home: { devices: [] }, configuration: { version: 1, devices: [] } };

function renderSection(onImported = () => {}) {
  return render(
    <I18nProvider>
      <ExchangeSection onImported={onImported} />
    </I18nProvider>,
  );
}

function upload(content: string) {
  const input = screen.getByLabelText("Importer un fichier");
  return userEvent.upload(input, new File([content], "maison.json", { type: "application/json" }));
}

describe("ExchangeSection", () => {
  beforeEach(() => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("propose l'export et vérifie un fichier avant de l'appliquer", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      calls.push(String(input));
      return Response.json({ issues: [], unknown_entities: ["sensor.pv"], applied: !String(input).includes("dry_run") });
    });
    const onImported = vi.fn();
    renderSection(onImported);

    expect(screen.getByRole("link", { name: "Exporter (JSON)" })).toHaveAttribute("href", "api/configuration/export");
    await upload(JSON.stringify(FILE));

    expect(await screen.findByText("Fichier valide : vous pouvez l'appliquer.")).toBeInTheDocument();
    expect(screen.getByText(/Capteurs absents de Home Assistant.*sensor\.pv/)).toBeInTheDocument();
    expect(onImported).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Appliquer l'import" }));

    expect(await screen.findByText(/Import appliqué/)).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledOnce();
    expect(calls).toEqual(["api/configuration/import?dry_run=true", "api/configuration/import"]);
  });

  it("montre les anomalies d'un fichier refusé, sans proposer de l'appliquer", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      Response.json({ issues: [{ code: "import_format", device: null, params: {} }], unknown_entities: [], applied: false }),
    );
    renderSection();

    await upload(JSON.stringify({ ...FILE, format: "autre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("n'est pas un export de la maison");
    expect(screen.queryByRole("button", { name: "Appliquer l'import" })).toBeNull();
  });

  it("refuse un fichier qui n'est pas du JSON", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    renderSection();

    await upload("pas du json");

    expect(await screen.findByRole("alert")).toHaveTextContent("n'est pas du JSON lisible");
    expect(fetch).not.toHaveBeenCalled();
  });
});
