// Formulaire d'une demande, celui de la feuille « Demander un appareil ».

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import RequestForm, { type RequestDevice } from "./RequestForm";

const DEVICES: RequestDevice[] = [
  { key: "washer", name: "Lave-linge" },
  { key: "dishwasher", name: "Lave-vaisselle" },
];

function mockApi(): unknown[] {
  const posted: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    if (init?.method === "POST") posted.push(JSON.parse(String(init.body)));
    return Response.json({});
  });
  return posted;
}

function renderForm(props: Partial<Parameters<typeof RequestForm>[0]> = {}) {
  const onAsked = vi.fn();
  render(
    <I18nProvider>
      <RequestForm devices={DEVICES} onAsked={onAsked} {...props} />
    </I18nProvider>,
  );
  return onAsked;
}

describe("RequestForm", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("demande un appareil, au plus tard un jour donné", async () => {
    const user = userEvent.setup();
    const posted = mockApi();
    const onAsked = renderForm();

    fireEvent.change(await screen.findByLabelText("Au plus tard le"), { target: { value: "2026-10-19" } });
    await user.click(screen.getByRole("button", { name: "Demander" }));

    expect(posted).toEqual([{ device: "washer", latest: "2026-10-19" }]);
    expect(onAsked).toHaveBeenCalledTimes(1);
  });

  it("propose de changer la date ou d'ajouter un cycle pour un appareil déjà demandé", async () => {
    const user = userEvent.setup();
    const posted = mockApi();
    renderForm({ waiting: ["washer"], waitingLatest: { washer: "2026-10-18" } });

    // Le lave-linge a une demande en attente : deux boutons, et l'aide qui les explique.
    await user.click(await screen.findByRole("button", { name: "Ajouter un cycle" }));
    expect(screen.queryByRole("button", { name: "Demander" })).toBeNull();
    // L'aide dit la date de cette demande (19/11/2026 : « déjà une demande », sans dire laquelle).
    expect(screen.getByText(/a déjà une demande en attente, au plus tard dimanche 18 octobre/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Changer la date" }));

    expect(posted).toEqual([
      { device: "washer", latest: null, another: true },
      { device: "washer", latest: null },
    ]);
  });

  it("ne dépose pas la demande d'un appareil dont le cycle n'est pas connu", async () => {
    // 20/11/2026 : chauffe-eau demandé, accepté, puis absent du plan.
    const user = userEvent.setup();
    const posted = mockApi();
    renderForm({ devices: [...DEVICES, { key: "heater", name: "Chauffe-eau", placeable: false }] });

    await user.selectOptions(await screen.findByLabelText("Appareil"), "heater");
    expect(screen.getByText(/ne connaît pas encore le cycle de cet appareil/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Demander" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Appareil"), "washer");
    expect(screen.getByRole("button", { name: "Demander" })).toBeEnabled();
    expect(posted).toEqual([]);
  });

  it("dit qu'une demande en attente est sans date", async () => {
    mockApi();
    renderForm({ waiting: ["washer"], waitingLatest: { washer: null } });

    expect(await screen.findByText(/a déjà une demande en attente, dès que possible/)).toBeInTheDocument();
  });

  it("demande un appareil à terminer avant une heure", async () => {
    // Issue 273 : lave-vaisselle demandé le soir, à finir avant midi.
    const user = userEvent.setup();
    const posted = mockApi();
    renderForm();

    await user.selectOptions(await screen.findByLabelText("Terminé avant"), "12");
    expect(screen.getByText(/Le cycle finira avant 12h, le jour où il tourne/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Demander" }));

    expect(posted).toEqual([{ device: "washer", latest: null, finish_hour: 12 }]);
    // Le champ revient à « sans heure limite » pour la demande suivante.
    expect(screen.getByLabelText("Terminé avant")).toHaveValue("");
  });

  it("dit l'heure limite de la demande en attente, et que la changer la remplace", async () => {
    mockApi();
    renderForm({ waiting: ["washer"], waitingLatest: { washer: "2026-10-18" }, waitingFinish: { washer: 12 } });

    expect(
      await screen.findByText(/Son heure limite : avant 12h\. « Changer la date » la remplace/),
    ).toBeInTheDocument();
  });
});
