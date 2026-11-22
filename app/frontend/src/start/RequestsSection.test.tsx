import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import RequestsSection, { type UserRequest } from "./RequestsSection";
import { REQUESTS_EVENT } from "./pendingLatest";

const DEVICES: { key: string; name: string; placeable?: boolean }[] = [
  { key: "washer", name: "Lave-linge" },
  { key: "dishwasher", name: "Lave-vaisselle" },
];

const OPEN: UserRequest = {
  id: 1,
  device: "dishwasher",
  created_at: "2026-10-17T08:00:00Z",
  latest: "2026-10-18",
  status: "open",
  launched_on: null,
  closed_at: null,
  planned_day: "2026-10-18",
};

type Call = { url: string; method: string; body: unknown };

function mockApi(devices = DEVICES, requests: UserRequest[] = [OPEN]): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url === "api/requests/devices") return Response.json(devices);
    if (url === "api/requests" && method === "GET") return Response.json(requests);
    return Response.json(OPEN);
  });
  return calls;
}

function renderSection() {
  render(
    <I18nProvider>
      <RequestsSection />
    </I18nProvider>,
  );
}

describe("RequestsSection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["fr-FR"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("liste les demandes en cours : l'appareil, son échéance, et ses boutons toujours visibles", async () => {
    // Ni formulaire ni texte d'introduction ici : une demande passe par « Demander un appareil ».
    const calls = mockApi();
    renderSection();

    const list = await screen.findByRole("list", { name: "Demandes en cours" });
    const row = within(list).getByText("Lave-vaisselle").closest("li") as HTMLElement;
    expect(row).toHaveTextContent("au plus tard dimanche 18 octobre");
    // Pas de dépliant : « Fait » et « Annuler » sont sous les yeux.
    expect(row.querySelector("details")).toBeNull();
    expect(within(row).getByRole("button", { name: "Fait" })).toBeVisible();
    expect(within(row).getByRole("button", { name: "Annuler" })).toBeVisible();
    expect(screen.queryByLabelText("Au plus tard le")).toBeNull();
    expect(screen.queryByText(/Demandez qu'un appareil tourne/)).toBeNull();

    // Une demande déposée ailleurs (feuille du menu) : la liste est relue.
    const reads = () => calls.filter((call) => call.url === "api/requests" && call.method === "GET").length;
    const before = reads();
    window.dispatchEvent(new Event(REQUESTS_EVENT));
    await vi.waitFor(() => expect(reads()).toBeGreaterThan(before));
  });

  it("dit l'heure limite d'une demande en cours", async () => {
    mockApi(DEVICES, [{ ...OPEN, device: "washer", finish_hour: 12 }]);
    renderSection();

    expect(await screen.findByText("au plus tard dimanche 18 octobre, terminé avant 12h")).toBeInTheDocument();
    expect(screen.getByText("Lave-linge")).toBeInTheDocument();
  });

  it("marque une demande faite ou l'annule", async () => {
    const user = userEvent.setup();
    const calls = mockApi(DEVICES, [OPEN, { ...OPEN, id: 2, device: "washer", status: "done", closed_at: "2026-10-16T20:00:00Z" }]);
    renderSection();

    await user.click(await screen.findByRole("button", { name: "Fait" }));
    await user.click(await screen.findByRole("button", { name: "Annuler" }));

    expect(calls.some((call) => call.url === "api/requests/1/done" && call.method === "POST")).toBe(true);
    expect(calls.some((call) => call.url === "api/requests/1" && call.method === "DELETE")).toBe(true);
    expect(screen.getByText("Lave-linge : fait").closest("details")?.open).toBe(false);
  });

  it("déclare lancé le cycle d'une demande placée dans le plan du jour", async () => {
    const user = userEvent.setup();
    const placed = { ...OPEN, cycle: "Lave-vaisselle #2" };
    const calls = mockApi(DEVICES, [
      placed,
      { ...OPEN, id: 2, device: "washer" }, // pas dans le plan du jour : rien à déclarer
      { ...placed, id: 3, declared: true },
    ]);
    renderSection();

    // Un seul bouton : ni pour la demande hors du plan du jour, ni pour celle déjà déclarée.
    await user.click(await screen.findByRole("button", { name: "C'est lancé" }));

    const call = calls.find((c) => c.url === "api/planning/launched");
    expect(call).toMatchObject({ method: "POST", body: { device: "Lave-vaisselle #2" } });
    // Un cycle après le premier : sa déclaration change le plan, le calcul est relancé.
    expect(calls.some((c) => c.url === "api/planning/run" && c.method === "POST")).toBe(true);
    expect(screen.getByText("marqué comme lancé")).toBeInTheDocument();
  });

  it("sous un jour à venir : une demande s'annule, mais ne peut pas avoir été faite ni lancée", async () => {
    // Onglets Demain et suivants de Planning (22/11/2026 : « Fait » proposé pour demain).
    mockApi(DEVICES, [{ ...OPEN, cycle: "Lave-vaisselle" }]);
    render(
      <I18nProvider>
        <RequestsSection future />
      </I18nProvider>,
    );

    expect(await screen.findByRole("button", { name: "Annuler" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fait" })).toBeNull();
    expect(screen.queryByRole("button", { name: "C'est lancé" })).toBeNull();
  });

  it("sous un jour : les demandes de ce jour seulement ; sous Aujourd'hui, celles pas encore placées aussi", async () => {
    // 22/11/2026 : la même liste sous tous les onglets, alors qu'on attend les demandes du jour.
    const monday = { ...OPEN, id: 1, device: "dishwasher", latest: "2026-10-19", planned_day: "2026-10-19" };
    const chosen = { ...OPEN, id: 2, device: "washer", latest: null, planned_day: "2026-10-18" };
    const waiting = { ...OPEN, id: 3, device: "dryer", latest: null, planned_day: null };
    const devices = [...DEVICES, { key: "dryer", name: "Sèche-linge" }];
    const show = (props: Parameters<typeof RequestsSection>[0]) => {
      mockApi(devices, [monday, chosen, waiting]);
      return render(
        <I18nProvider>
          <RequestsSection {...props} />
        </I18nProvider>,
      );
    };
    const names = async () => {
      const list = await screen.findByRole("list", { name: "Demandes en cours" });
      return within(list)
        .getAllByRole("listitem")
        .map((item) => item.querySelector(".requests-name")?.textContent);
    };

    // Un jour à venir : la demande que le calcul y place, rien d'autre.
    const tomorrow = show({ day: "2026-10-18", future: true });
    expect(await names()).toEqual(["Lave-linge"]);
    expect(screen.queryByText("Dernières demandes")).toBeNull();
    tomorrow.unmount();

    // Aujourd'hui : rien n'y est placé, mais la demande pas encore placée s'y montre.
    const today = show({ day: "2026-10-17", today: true });
    expect(await names()).toEqual(["Sèche-linge"]);
    expect(screen.getByText("dès que possible · pas encore placée")).toBeInTheDocument();
    today.unmount();

    // Semaine : toutes, avec le jour choisi par le calcul pour une demande sans date.
    show({ future: true });
    expect(await names()).toEqual(["Lave-vaisselle", "Lave-linge", "Sèche-linge"]);
    expect(screen.getByText("dès que possible · prévu dimanche 18 octobre")).toBeInTheDocument();
    expect(screen.getByText("au plus tard lundi 19 octobre")).toBeInTheDocument();
  });

  it("sous Hier : la demande lancée hier, même close, sans bouton", async () => {
    const done = { ...OPEN, id: 5, device: "washer", status: "done" as const, launched_on: "2026-10-16", planned_day: null };
    mockApi(DEVICES, [OPEN, done]);
    render(
      <I18nProvider>
        <RequestsSection day="2026-10-16" />
      </I18nProvider>,
    );

    const row = (await screen.findByText("Lave-linge")).closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Lave-lingefait");
    expect(within(row).queryByRole("button")).toBeNull();
    expect(screen.queryByText("Lave-vaisselle")).toBeNull(); // demande d'un autre jour
  });

  it("dit quand aucune demande ne concerne le jour affiché", async () => {
    mockApi(DEVICES, [{ ...OPEN, planned_day: "2026-10-18" }]);
    render(
      <I18nProvider>
        <RequestsSection day="2026-10-20" future />
      </I18nProvider>,
    );

    expect(await screen.findByText("Aucune demande ce jour-là.")).toBeInTheDocument();
  });

  it("ne montre rien sans appareil à lancer", async () => {
    const calls = mockApi([], []);
    renderSection();

    await vi.waitFor(() => expect(calls.length).toBe(2));
    expect(screen.queryByText("Mes demandes")).not.toBeInTheDocument();
  });
});
