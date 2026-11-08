import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import DiagnosticScreen from "./DiagnosticScreen";
import { formatAge } from "./format";
import type { Diagnostic, Resources } from "./types";
import type { Problem } from "./ProblemsSection";
import { silentEntities } from "./warnings";

const NOW = "2026-10-16T08:00:00Z";

const HEALTHY: Diagnostic = {
  generated_at: NOW,
  memory_bytes: 84_000_000,
  started_at: "2026-10-15T08:00:00Z",
  written_bytes: 2_000_000_000,
  ingestion: {
    running: true,
    entities: [
      {
        entity_id: "sensor.pv_power",
        role: "PowerProduced",
        last_value: 1520,
        last_time: "2026-10-16T07:58:00Z",
        received: 40,
        kept: 30,
      },
      {
        entity_id: "sensor.grid_energy",
        role: "EnergyImported",
        last_value: 12.5,
        last_time: "2026-10-16T07:00:00Z",
        received: 5,
        kept: 5,
      },
    ],
    received: 45,
    written: 35,
    pending: 0,
    last_batch_at: "2026-10-16T07:59:55Z",
    last_error: null,
    days: ["2026-10-16"],
    backfilled: 0,
    last_backfill_at: null,
  },
  today: { "sensor.pv_power": 30, "sensor.grid_energy": 5 },
  aggregation: {
    running: true,
    last_run_at: NOW,
    written: 1200,
    complete_until: { PT15M: "2026-10-16T07:45:00Z", PT1H: "2026-10-16T07:00:00Z" },
    last_error: null,
    history: { imported: 2, pending: [], without_statistics: [], since: { PT1H: "2023-09-01T08:00:00Z" } },
  },
  maintenance: {
    running: true,
    in_progress: false,
    next_run_at: "2026-10-17T01:30:00Z",
    last_run: null,
    last_error: null,
    retention: { raw_days: 3, quarter_days: 35, hour_days: null },
    disk: { raw_bytes: 1_000_000_000, graph_bytes: 2_000_000_000, database_bytes: 100_000 },
  },
  planning: {
    running: true,
    enabled: true,
    next_run_at: "2026-10-16T07:59:00Z",
    last_run_at: "2026-10-16T06:59:00Z",
    last_success_at: "2026-10-16T06:59:00Z",
    last_report: {
      day: "2026-10-16",
      started_at: "2026-10-16T06:59:00Z",
      manual: false,
      seconds_today: 6.2,
      seconds_tomorrow: 4.1,
      seconds_horizon: 9.7,
      horizon_days: 5,
      errors: [],
    },
    last_error: null,
  },
  issues: [],
};

const RESOURCES: Resources = {
  cpu_percent: 2.5,
  cpu_peak_percent: 85,
  cpu_cores: 4,
  memory_bytes: 180_000_000,
  memory_peak_bytes: 210_000_000,
  memory_limit_bytes: 4_000_000_000,
  disk_used_bytes: 1_250_000_000,
  disk_free_bytes: 20_000_000_000,
  disk_total_bytes: 32_000_000_000,
  measured_s: 3600,
};

function mockApi(diagnostic: Diagnostic, problems: Problem[] = []) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "api/diagnostic") return Response.json(diagnostic);
    if (url === "api/diagnostic/resources") return Response.json(RESOURCES);
    if (url === "api/diagnostic/problems") return Response.json(problems);
    if (url === "api/diagnostic/report") return Response.json({ format: "wattslot/report", problems: [] });
    return new Response(null, { status: 404 });
  });
}

function renderScreen(onNavigate = vi.fn()) {
  render(
    <I18nProvider>
      <DiagnosticScreen onNavigate={onNavigate} />
    </I18nProvider>,
  );
  return onNavigate;
}

describe("silentEntities", () => {
  it("reprend les entités muettes calculées par le serveur", () => {
    const entity = HEALTHY.ingestion!.entities[1].entity_id;
    expect(silentEntities(HEALTHY)).toEqual([]);
    expect(silentEntities({ ...HEALTHY, silent: [entity] })).toEqual([entity]);
  });
});

describe("formatAge", () => {
  it("donne l'âge en langage courant", () => {
    expect(formatAge("en", "2026-10-16T07:58:00Z", NOW)).toBe("2 minutes ago");
    expect(formatAge("fr", "2026-10-16T05:00:00Z", NOW)).toBe("il y a 3 heures");
    expect(formatAge("en", null, NOW)).toBe("—");
  });
});

describe("DiagnosticScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("affiche l'état, les entités et les volumes", async () => {
    mockApi(HEALTHY);

    renderScreen();

    expect(await screen.findByText("Nothing to report: everything works.")).toBeInTheDocument();
    expect(await screen.findByText("sensor.pv_power")).toBeInTheDocument();
    expect(screen.getByText("1,520 W")).toBeInTheDocument();
    expect(screen.getByText("12.5 kWh")).toBeInTheDocument();
    expect(screen.getByText("2,000 MB")).toBeInTheDocument();
    expect(screen.getByText("Plan computations")).toBeInTheDocument();
    expect(screen.getByText(/2,000 MB since start .*, i\.e\. 2 GB per day/)).toBeInTheDocument();
    expect(screen.getByText(/6.2 s for today, 20 s in all/)).toBeInTheDocument();
    expect(globalThis.fetch).toHaveBeenCalledWith("api/diagnostic", expect.anything());
  });

  it("montre processeur, mémoire et disque", async () => {
    mockApi(HEALTHY);

    renderScreen();

    expect(await screen.findByText("2.5%")).toBeInTheDocument();
    expect(screen.getByText("Average over 15 minutes · peak since start: 85% · available cores: 4")).toBeInTheDocument();
    expect(screen.getByText("180 MB")).toBeInTheDocument();
    expect(screen.getByText("peak since start: 210 MB · limit: 4 GB")).toBeInTheDocument();
    expect(screen.getByText("1.3 GB")).toBeInTheDocument();
    expect(screen.getByText("Application data · free on the host: 20 GB of 32 GB")).toBeInTheDocument();
  });

  it("rappelle les anomalies de configuration", async () => {
    const diagnostic: Diagnostic = {
      ...HEALTHY,
      issues: [
        {
          device: "Battery",
          entity_id: null,
          issue: { code: "battery_capacity_missing", params: {} },
        },
      ],
    };
    mockApi(diagnostic);

    renderScreen();

    expect(await screen.findByText("Battery: Unknown battery capacity: please enter it.")).toBeInTheDocument();
  });

  it("signale un état illisible", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(null, { status: 500 }));

    renderScreen();

    expect(await screen.findByText("The status could not be read.")).toBeInTheDocument();
    expect(screen.getByText("Unable to read the problems.")).toBeInTheDocument();
  });

  it("dit ce qui ne va pas, le geste et où le faire", async () => {
    mockApi(HEALTHY, [
      {
        code: "no_forecast",
        severity: "blocking",
        params: {},
        target: "home#solar",
        doc: "https://www.home-assistant.io/integrations/forecast_solar/",
      },
      {
        code: "sensor_missing",
        severity: "degraded",
        params: { device: "Roof", role: "EnergyProduced", entity: "sensor.gone" },
        target: "home",
        doc: null,
      },
      {
        code: "configuration_issue",
        severity: "degraded",
        params: { issue: "after_unknown", device: "Dryer", after: "x" },
        target: "home",
        doc: null,
      },
    ]);
    const onNavigate = renderScreen();

    const blocking = await screen.findByText(/No solar forecast/);
    expect(blocking.closest("li")).toHaveTextContent("Blocks the plan");
    expect(screen.getByText(/Roof: the "Energy produced" sensor \(sensor\.gone\) no longer exists/)).toBeInTheDocument();
    expect(screen.getByText(/Dryer: the device to follow \(x\) is not in the home/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Documentation" })[0]).toHaveAttribute(
      "href",
      "https://www.home-assistant.io/integrations/forecast_solar/",
    );
    await userEvent.click(screen.getAllByRole("button", { name: "Go there" })[0]);
    expect(onNavigate).toHaveBeenCalledWith("home#solar");
    expect(document.querySelector("details")?.open).toBe(false); // détail technique replié
  });

  it("résume les problèmes et replie une longue liste", async () => {
    const watch = (entity: string): Problem => ({
      code: "sensor_silent",
      severity: "watch",
      params: { device: "Roof", role: "EnergyProduced", entity },
      target: "home",
      doc: null,
    });
    mockApi(HEALTHY, [
      { code: "no_forecast", severity: "blocking", params: {}, target: "home#solar", doc: null },
      ...["sensor.a", "sensor.b", "sensor.c", "sensor.d"].map(watch),
    ]);
    renderScreen();

    expect(await screen.findByText("5 problem(s) to look at")).toBeInTheDocument();
    expect(screen.getByText("Blocks the plan: 1 · To watch: 4")).toBeInTheDocument();
    // Les trois premiers seulement, les plus graves d'abord ; les autres se déplient.
    expect(screen.getAllByRole("listitem").filter((item) => item.classList.contains("problem"))).toHaveLength(3);
    await userEvent.click(screen.getByRole("button", { name: "Show the 2 others" }));
    expect(screen.getAllByRole("listitem").filter((item) => item.classList.contains("problem"))).toHaveLength(5);
    await userEvent.click(screen.getByRole("button", { name: "Show less" }));
    expect(screen.getAllByRole("listitem").filter((item) => item.classList.contains("problem"))).toHaveLength(3);
  });

  it("nomme le saut de compteur derrière un jour non calculé", async () => {
    mockApi(HEALTHY, [
      {
        code: "impossible_data",
        severity: "degraded",
        params: {
          day: "2026-10-23",
          hour: "20",
          kwh: "10674.1",
          limit: "11.5",
          device: "Grid",
          entity: "sensor.grid_import",
          when: "2026-10-16",
          when_hour: "20",
          source_kwh: "64045",
          until: "2026-11-27",
        },
        target: null,
        doc: null,
      },
    ]);
    renderScreen();

    const problem = await screen.findByText(/Forecasts stopped before Friday, October 23/);
    expect(problem.closest("li")).toHaveTextContent(
      'the sensor "Grid" (sensor.grid_import) counted 64,045 kWh in one hour on Friday, October 16 at 20:00',
    );
    expect(problem.closest("li")).toHaveTextContent("expected at 20:00 (10,674 kWh)");
    expect(problem.closest("li")).toHaveTextContent("(11.5 kWh)");
    expect(problem.closest("li")).toHaveTextContent("stay wrong until Friday, November 27.");
    expect(problem.closest("li")).toHaveTextContent("Check the history of this sensor in Home Assistant");
  });

  it("reconnecte Home Assistant depuis « Vérifier à nouveau »", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url === "api/connection/retry") return Response.json({});
      if (url === "api/diagnostic") return Response.json(HEALTHY);
      if (url.startsWith("api/diagnostic/problems"))
        return Response.json([
          {
            code: "ha_disconnected",
            severity: "blocking",
            params: { error_code: "starting" },
            target: "connection",
            doc: "https://www.home-assistant.io/docs/authentication/",
          },
        ]);
      if (url === "api/diagnostic/report") return Response.json({ format: "wattslot/report", problems: [] });
      return new Response(null, { status: 404 });
    });
    renderScreen();

    // Le code d'erreur devient une phrase, pas un message technique.
    expect(await screen.findByText(/Home Assistant has restarted and is not ready yet/)).toBeInTheDocument();
    expect(screen.getByText(/Home Assistant does not respond/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByText(/Home Assistant does not respond/);

    expect(calls).toContain("POST api/connection/retry");
    // Le second passage demande au serveur de relire d'abord les états de HA.
    expect(calls).toContain("GET api/diagnostic/problems");
    expect(calls).toContain("GET api/diagnostic/problems?refresh=true");
  });

  it("montre le rapport avant de le télécharger", async () => {
    mockApi(HEALTHY);
    const created = vi.fn(() => "blob:report");
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    renderScreen();

    await userEvent.click(await screen.findByRole("button", { name: "Prepare a report" }));
    expect(await screen.findByLabelText("Report preview")).toHaveTextContent('"format": "wattslot/report"');
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(created).toHaveBeenCalledOnce();
  });
});
