import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError, getJson, putJson } from "../api";
import Advanced, { Hint } from "../common/Advanced";
import Glossary from "../common/Glossary";
import { useI18n } from "../i18n/I18nProvider";
import Button from "../ui/Button";
import StateMessage from "../ui/StateMessage";
import AddDevice from "./AddDevice";
import BatteryEditor from "./BatteryEditor";
import type { Configuration, DeviceSettings as DeviceSettingsType, TaskRules } from "./configuration";
import DeviceSettings from "./DeviceSettings";
import ExchangeSection from "./ExchangeSection";
import { Devices, Essentials, type Essential, type HomeData } from "./HomeSummary";
import ObjectiveEditor from "./ObjectiveEditor";
import PanelsEditor from "./PanelsEditor";
import SettingsSheet from "./SettingsSheet";
import TariffEditor from "./TariffEditor";
import TemplateSection from "./TemplateSection";
import { buildDraft, mergeDraft, toModel, type DraftDevice } from "./draft";
import {
  DEVICE_KINDS,
  type DeviceKind,
  type DeviceType,
  type DeviceTypes,
  type LibraryType,
  type HomeModel,
  type HomeProposal,
  type Issue,
} from "./types";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; energyDashboard: boolean }
  | { status: "error"; code: "not_connected" | "failed" };

type SaveState = "idle" | "saving" | "saved" | "failed";

type LoadResult =
  | { ok: true; draft: DraftDevice[]; energyDashboard: boolean; types: DeviceType[]; library: LibraryType[] }
  | { ok: false; code: "not_connected" | "failed" };

async function loadHome(refresh: boolean): Promise<LoadResult> {
  try {
    const [proposal, saved, types] = await Promise.all([
      getJson<HomeProposal>(`api/home/proposals${refresh ? "?refresh=true" : ""}`),
      getJson<HomeModel>("api/home"),
      // Types propres : sans eux, l'écran reste utilisable avec ceux de la bibliothèque.
      getJson<DeviceTypes>("api/home/types").catch(() => ({ parents: [], types: [], library: [] })),
    ]);
    return {
      ok: true,
      draft: buildDraft(proposal.devices, saved),
      energyDashboard: proposal.energy_dashboard,
      types: types.types,
      library: types.library,
    };
  } catch (error) {
    const notConnected = error instanceof ApiError && error.status === 503;
    return { ok: false, code: notConnected ? "not_connected" : "failed" };
  }
}

// Vue en graphe : React Flow n'est chargé que si on la demande (lot 2t.3).
const HomeGraph = lazy(() => import("./HomeGraph"));

// Onglet ouvert de la page principale, gardé dans le navigateur comme celui de Planning.
export const TAB_KEY = "home.tab";
const TABS = ["essentials", "devices", "more"] as const;
type Tab = (typeof TABS)[number];

function savedTab(): Tab {
  try {
    const found = window.localStorage.getItem(TAB_KEY);
    return (TABS as readonly string[]).includes(found ?? "") ? (found as Tab) : "essentials";
  } catch {
    return "essentials";
  }
}

function rememberTab(tab: Tab) {
  try {
    window.localStorage.setItem(TAB_KEY, tab);
  } catch {
    // stockage indisponible : rien à garder
  }
}

// Pages de Ma maison (lot 6b.5) : la page principale en onglets, puis les écrans experts ouverts
// depuis l'onglet « Avancé ».
export type HomePage = "main" | "devices" | "templates" | "backup" | "graph";

export default function HomeScreen({
  page = "main",
  onNavigate,
  more,
  anchor = null,
  onAnchor,
}: {
  page?: HomePage;
  onNavigate: (target: string) => void;
  // Liens des écrans experts, fournis par l'application : rendus dans l'onglet « Avancé ».
  more?: ReactNode;
  // Réglage demandé par un lien (« home#tariff », « home#settings-washer ») : sa feuille s'ouvre.
  anchor?: string | null;
  onAnchor?: () => void;
}) {
  const { t } = useI18n();
  const [version, setVersion] = useState(0); // relit les réglages après un enregistrement
  const changed = () => setVersion((count) => count + 1);

  if (page === "devices") return <HomeEditor onSaved={changed} onNavigate={onNavigate} />;
  if (page === "templates") return <TemplateSection version={version} onApplied={changed} />;
  if (page === "backup") return <ExchangeSection onImported={changed} />;
  if (page === "graph") {
    return (
      <Suspense fallback={<p>{t("graph.loading")}</p>}>
        <HomeGraph />
      </Suspense>
    );
  }
  return <HomeMain onNavigate={onNavigate} more={more} anchor={anchor} onAnchor={onAnchor} />;
}

type MainLoad = { status: "loading" } | { status: "error" } | ({ status: "ready" } & HomeData);

// Feuille ouverte : un réglage de « L'essentiel » ou les réglages d'un appareil.
type Open = { kind: Essential } | { kind: "device"; key: string };

const ESSENTIALS: readonly string[] = ["objective", "tariff", "solar", "battery"];

// Reprise des règles des tâches de HA : enregistrées, aucune, HA absent, échec.
type RulesState = "idle" | "loading" | "applied" | "none" | "not_connected" | "failed";

// Page principale (refonte de Ma maison) : trois onglets courts, et chaque réglage dans sa feuille,
// enregistré seul. Rien n'est déplié d'avance : une ligne par réglage ou par appareil.
function HomeMain({
  onNavigate,
  more,
  anchor,
  onAnchor,
}: {
  onNavigate: (target: string) => void;
  more?: ReactNode;
  anchor: string | null;
  onAnchor?: () => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>(savedTab);
  const [load, setLoad] = useState<MainLoad>({ status: "loading" });
  const [attempt, setAttempt] = useState(0); // « Réessayer »
  const [open, setOpen] = useState<Open | null>(null);
  const [saved, setSaved] = useState(false);
  const [rules, setRules] = useState<RulesState>("idle");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<HomeModel>("api/home", controller.signal),
      getJson<Configuration>("api/configuration", controller.signal),
    ])
      .then(([home, configuration]) => setLoad({ status: "ready", devices: home.devices, configuration }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [attempt]);

  const choose = (next: Tab) => {
    setTab(next);
    rememberTab(next);
  };

  // Lien vers un réglage : son onglet, puis sa feuille, une fois la maison lue (état ajusté au
  // rendu, une fois par lien).
  const [handled, setHandled] = useState<string | null>(null);
  if (anchor && anchor !== handled && load.status === "ready") {
    setHandled(anchor);
    if (ESSENTIALS.includes(anchor)) {
      setTab("essentials");
      setOpen({ kind: anchor as Essential });
    } else if (anchor.startsWith("settings-")) {
      setTab("devices");
      setOpen({ kind: "device", key: anchor.slice("settings-".length) });
    }
  }
  useEffect(() => {
    if (anchor && anchor === handled) onAnchor?.();
  }, [anchor, handled, onAnchor]);

  const data: HomeData | null =
    load.status === "ready" ? { devices: load.devices, configuration: load.configuration } : null;
  const names = new Map(data?.devices.map((device) => [device.key, device.name]));
  const empty = data !== null && data.configuration.devices.length === 0;

  const show = (next: Open) => {
    setSaved(false);
    setOpen(next);
  };

  const onSaved = (configuration: Configuration) => {
    if (data) setLoad({ status: "ready", ...data, configuration });
    setOpen(null);
    setSaved(true);
  };

  // Reprise des règles des descriptions JSON des tâches de HA (lot 3.5), enregistrées aussitôt :
  // chaque appareil concerné les montre ensuite dans sa feuille.
  const onImportRules = async (current: HomeData) => {
    setRules("loading");
    try {
      const found = await getJson<TaskRules[]>("api/configuration/task-rules-proposal");
      const byDevice = new Map(found.map((r) => [r.key, r]));
      const { configuration } = current;
      if (!configuration.devices.some((s) => byDevice.has(s.key) && s.behavior === "CycleBehavior")) {
        setRules("none");
        return;
      }
      const next = await putJson<Configuration>("api/configuration", {
        ...configuration,
        devices: configuration.devices.map((settings) => {
          const proposed = byDevice.get(settings.key);
          if (!proposed || settings.behavior !== "CycleBehavior") return settings;
          return {
            ...settings,
            recurrence: proposed.recurrence ?? settings.recurrence,
            after: proposed.after ?? settings.after,
            default: false,
          };
        }),
      });
      setLoad({ status: "ready", ...current, configuration: next });
      setRules("applied");
    } catch (error) {
      setRules(error instanceof ApiError && error.status === 503 ? "not_connected" : "failed");
    }
  };

  // Maison pas encore lue ou illisible : « Avancé » reste ouvert (sauvegarde, modèles…).
  const state =
    load.status === "loading" ? (
      <StateMessage kind="loading" title={t("home_summary.loading")} />
    ) : load.status === "error" ? (
      <StateMessage
        kind="error"
        title={t("home_summary.error")}
        onRetry={() => {
          setLoad({ status: "loading" });
          setAttempt((count) => count + 1);
        }}
      />
    ) : null;

  return (
    <>
      <div className="view-tabs home-tabs" role="tablist" aria-label={t("nav.home")}>
        {TABS.map((kind) => (
          <button key={kind} type="button" role="tab" aria-selected={tab === kind} onClick={() => choose(kind)}>
            {t(`home.tabs.${kind}`)}
          </button>
        ))}
      </div>
      {saved && <p role="status">{t("configuration.saved")}</p>}
      <section className="home-summary" role="tabpanel" aria-label={t(`home.tabs.${tab}`)}>
        {tab !== "more" && state}
        {tab === "essentials" && data && <Essentials data={data} onOpen={(kind) => show({ kind })} />}
        {tab === "devices" &&
          data &&
          (empty ? (
            <StateMessage kind="empty" title={t("configuration.empty")} />
          ) : (
            <Devices
              data={data}
              onOpen={(key) => show({ kind: "device", key })}
              onAdd={() => onNavigate("devices#add-device")}
            />
          ))}
        {tab === "more" && (
          <>
            {data && !empty && (
              <p>
                <Button onClick={() => void onImportRules(data)} disabled={rules === "loading"}>
                  {t("configuration.import_rules")}
                </Button>
              </p>
            )}
            {rules !== "idle" && rules !== "loading" && <p role="status">{t(`configuration.rules.${rules}`)}</p>}
            {more}
            <Glossary />
          </>
        )}
      </section>
      {open && data && (
        <HomeSheet open={open} data={data} names={names} onClose={() => setOpen(null)} onSaved={onSaved} />
      )}
    </>
  );
}

// Feuille d'un réglage : l'éditeur de la partie concernée de la configuration.
function HomeSheet({
  open,
  data,
  names,
  onClose,
  onSaved,
}: {
  open: Open;
  data: HomeData;
  names: Map<string, string>;
  onClose: () => void;
  onSaved: (configuration: Configuration) => void;
}) {
  const { t } = useI18n();
  const { devices, configuration } = data;
  const sheet = (title: string, edit: (draft: Configuration, change: (next: Configuration) => void) => ReactNode) => (
    <SettingsSheet title={title} configuration={configuration} names={names} onClose={onClose} onSaved={onSaved}>
      {edit}
    </SettingsSheet>
  );
  // Réglages d'un appareil modifiés : ils ne sont plus ceux par défaut de son type.
  const withDevice = (draft: Configuration, key: string, update: Partial<DeviceSettingsType>): Configuration => ({
    ...draft,
    devices: draft.devices.map((settings) =>
      settings.key === key ? { ...settings, ...update, default: false } : settings,
    ),
  });

  switch (open.kind) {
    case "objective":
      return sheet(t("objective.title"), (draft, change) => (
        <div className="expert-form">
          <ObjectiveEditor objective={draft.objective ?? null} onChange={(objective) => change({ ...draft, objective })} />
        </div>
      ));
    case "tariff":
      return sheet(t("tariff.title"), (draft, change) => (
        <div className="expert-form">
          <TariffEditor tariff={draft.tariff ?? null} onChange={(tariff) => change({ ...draft, tariff })} />
        </div>
      ));
    case "battery": {
      // Batteries de la maison, vues comme une seule par le calcul.
      const capacity = devices.filter((d) => d.kind === "Battery").reduce((sum, d) => sum + (d.capacity_kwh ?? 0), 0);
      return sheet(t("battery.title"), (draft, change) => (
        <div className="expert-form">
          <BatteryEditor battery={draft.battery ?? null} capacityKwh={capacity} onChange={(battery) => change({ ...draft, battery })} />
        </div>
      ));
    }
    case "solar":
      // Une installation ou plusieurs : les panneaux de chacune.
      return sheet(t("home_summary.panels.title"), (draft, change) => (
        <div className="expert-form">
          {draft.devices
            .filter((settings) => settings.behavior === "ProductionBehavior")
            .map((settings) => (
              <PanelsEditor
                key={settings.key}
                panels={settings.panels ?? null}
                name={names.get(settings.key) ?? settings.key}
                onChange={(panels) => change(withDevice(draft, settings.key, { panels }))}
              />
            ))}
        </div>
      ));
    case "device": {
      const key = open.key;
      if (!configuration.devices.some((settings) => settings.key === key)) return null;
      const name = names.get(key) ?? key;
      const kind = devices.find((d) => d.key === key)?.kind ?? null;
      return sheet(name, (draft, change) => (
        <DeviceSettings
          settings={draft.devices.find((s) => s.key === key)!}
          kind={kind}
          name={name}
          others={draft.devices
            .filter((other) => other.key !== key && other.behavior === "CycleBehavior")
            .map((other) => ({ key: other.key, name: names.get(other.key) ?? other.key }))}
          onChange={(update) => change(withDevice(draft, key, update))}
        />
      ));
    }
  }
}

function HomeEditor({ onSaved, onNavigate }: { onSaved: () => void; onNavigate: (target: string) => void }) {
  const { t } = useI18n();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [draft, setDraft] = useState<DraftDevice[]>([]);
  const [save, setSave] = useState<SaveState>("idle");
  const [types, setTypes] = useState<DeviceType[]>([]);
  const [library, setLibrary] = useState<LibraryType[]>([]);

  const apply = useCallback((result: LoadResult, keepChoices: boolean) => {
    if (!result.ok) {
      setLoad({ status: "error", code: result.code });
      return;
    }
    setDraft((previous) => (keepChoices ? mergeDraft(previous, result.draft) : result.draft));
    setTypes(result.types);
    setLibrary(result.library);
    setLoad({ status: "ready", energyDashboard: result.energyDashboard });
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadHome(false).then((result) => {
      if (!cancelled) apply(result, false);
    });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  const onRefresh = async () => apply(await loadHome(true), true);

  const update = (key: string, change: Partial<DraftDevice>) => {
    setSave("idle");
    setDraft((devices) =>
      devices.map((device) => (device.key === key ? { ...device, ...change } : device)),
    );
  };

  const toggleSensor = (key: string, index: number, included: boolean) => {
    setSave("idle");
    setDraft((devices) =>
      devices.map((device) =>
        device.key === key
          ? {
              ...device,
              sensors: device.sensors.map((sensor, i) =>
                i === index ? { ...sensor, included } : sensor,
              ),
            }
          : device,
      ),
    );
  };

  const onSave = async () => {
    setSave("saving");
    try {
      await putJson<HomeModel>("api/home", toModel(draft));
      setSave("saved");
      onSaved();
    } catch {
      setSave("failed");
    }
  };

  if (load.status === "loading") return <p>{t("home.loading")}</p>;
  if (load.status === "error") return <p role="alert">{t(`home.error.${load.code}`)}</p>;
  if (!load.energyDashboard) return <p role="alert">{t("home.no_energy_dashboard")}</p>;

  const issueCount = draft.reduce(
    (count, device) =>
      count + device.issues.length + device.sensors.reduce((n, s) => n + s.issues.length, 0),
    0,
  );

  return (
    <section aria-labelledby="home-title" className="expert-form">
      <h2 className="visually-hidden" id="home-title">{t("home.title")}</h2>
      <p>{t("home.intro")}</p>
      {issueCount > 0 && <p role="status">{t("home.issue_count", { count: issueCount })}</p>}
      <button type="button" onClick={() => void onRefresh()}>
        {t("home.refresh")}
      </button>

      {draft.map((device) => (
        <article key={device.key} id={`device-${device.key}`} aria-label={device.name} className="card expert-card">
          <label>
            <input
              type="checkbox"
              checked={device.included}
              onChange={(event) => update(device.key, { included: event.target.checked })}
            />{" "}
            {t("home.include")}
          </label>
          <Hint text={t("home.include_hint")} />
          <label>
            {t("home.name")}{" "}
            <input
              value={device.name}
              onChange={(event) => update(device.key, { name: event.target.value })}
            />
          </label>
          <label>
            {t("home.kind")}{" "}
            <select
              value={device.customType ? `custom:${device.customType}` : device.kind}
              onChange={(event) => update(device.key, kindChoice(event.target.value, types))}
            >
              {DEVICE_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {t(`kind.${kind}`)}
                </option>
              ))}
              {types.map((own) => (
                <option key={own.key} value={`custom:${own.key}`}>
                  {t("home.custom_kind", { name: own.name, parent: t(`kind.${own.parent}`) })}
                </option>
              ))}
            </select>
          </label>
          <Hint text={t("home.kind_hint")} />
          {device.kind === "Battery" && (
            <label>
              {t("home.capacity")}{" "}
              <input
                type="number"
                min="0"
                step="0.01"
                value={device.capacityKwh ?? ""}
                onChange={(event) =>
                  update(device.key, {
                    capacityKwh: event.target.value === "" ? null : Number(event.target.value),
                  })
                }
              />
              {device.capacitySource && (
                <> {t("home.capacity_source", { entity: device.capacitySource })}</>
              )}
            </label>
          )}
          <IssueList issues={device.issues} />
          {device.included && (
            <button type="button" className="link" onClick={() => onNavigate(`home#settings-${device.key}`)}>
              {t("home.to_settings")}
            </button>
          )}
          <p>{t("home.sensors_summary", { count: device.sensors.filter((sensor) => sensor.included).length })}</p>
          <Advanced modified={device.sensors.some((sensor) => !sensor.included || sensor.issues.length > 0)}>
          <ul>
            {device.sensors.map((sensor, index) => (
              <li key={`${sensor.role}-${sensor.entity_id}`}>
                <input
                  type="checkbox"
                  aria-label={t("home.keep_sensor", { entity: sensor.entity_id })}
                  checked={sensor.included}
                  onChange={(event) => toggleSensor(device.key, index, event.target.checked)}
                />{" "}
                {t(`role.${sensor.role}`)} : <code>{sensor.entity_id}</code>
                {sensor.unit && ` (${sensor.unit})`}
                {sensor.resets_daily && ` — ${t("home.resets_daily")}`}
                <IssueList issues={sensor.issues} />
              </li>
            ))}
          </ul>
          </Advanced>
        </article>
      ))}

      <div id="add-device">
      <AddDevice
        library={library}
        types={types}
        existing={draft.map((device) => device.key)}
        onAdd={(device) => {
          setSave("idle");
          setDraft((devices) => [...devices, device]);
        }}
      />
      </div>{" "}
      <button type="button" onClick={() => void onSave()} disabled={save === "saving"}>
        {t("home.save")}
      </button>
      {save === "saved" && <p role="status">{t("home.saved")}</p>}
      {save === "failed" && <p role="alert">{t("home.save_failed")}</p>}
    </section>
  );
}

// Choix du type : un type de la bibliothèque, ou un type propre (et alors son parent).
function kindChoice(value: string, types: DeviceType[]): { kind: DeviceKind; customType: string | null } {
  const own = value.startsWith("custom:") ? types.find((t) => t.key === value.slice(7)) : undefined;
  return own ? { kind: own.parent, customType: own.key } : { kind: value as DeviceKind, customType: null };
}

function IssueList({ issues }: { issues: Issue[] }) {
  const { t } = useI18n();
  if (issues.length === 0) return null;
  return (
    <ul>
      {issues.map((issue, index) => (
        <li key={`${issue.code}-${index}`} className="issue">
          {t(`issue.${issue.code}`, issue.params)}
        </li>
      ))}
    </ul>
  );
}
