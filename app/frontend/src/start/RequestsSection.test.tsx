import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import RequestsSection, { type UserRequest } from "./RequestsSection";

const DEVICES = [
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

  it("demande un appareil, au plus tard un jour donné", async () => {
    const user = userEvent.setup();
    const calls = mockApi();
    renderSection();

    expect(await screen.findByText(/Lave-vaisselle : au plus tard dimanche 18 octobre/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Au plus tard le"), { target: { value: "2026-10-19" } });
    await user.click(screen.getByRole("button", { name: "Demander" }));

    const posted = calls.find((call) => call.method === "POST");
    expect(posted).toEqual({
      url: "api/requests",
      method: "POST",
      body: { device: "washer", latest: "2026-10-19" },
    });
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

  it("ne montre rien sans appareil à lancer", async () => {
    const calls = mockApi([], []);
    renderSection();

    await vi.waitFor(() => expect(calls.length).toBe(2));
    expect(screen.queryByText("Mes demandes")).not.toBeInTheDocument();
  });
});
