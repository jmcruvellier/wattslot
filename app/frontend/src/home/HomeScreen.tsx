import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError, getJson, putJson } from "../api";
import Advanced, { Hint } from "../common/Advanced";
import Glossary from "../common/Glossary";
import { reveal } from "../common/reveal";
import { useI18n } from "../i18n/I18nProvider";
import AddDevice from "./AddDevice";
import HomeSummary from "./HomeSummary";
import ConfigurationSection from "./ConfigurationSection";
import ExchangeSection from "./ExchangeSection";
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

// « Réglages détaillés » ouverts ou repliés (lot 6b.5), gardé dans le navigateur.
export const DETAILS_KEY = "home.details";

function savedDetails(): boolean {
  try {
    return window.localStorage.getItem(DETAILS_KEY) === "open";
  } catch {
    return false;
  }
}

function rememberDetails(open: boolean) {
  try {
    window.localStorage.setItem(DETAILS_KEY, open ? "open" : "closed");
  } catch {
    // stockage indisponible : rien à garder
  }
}

// Pages de Ma maison (lot 6b.5) : la maison en phrases et ses réglages détaillés, puis les
// écrans experts rangés sous « Pour aller plus loin ».
export type HomePage = "main" | "devices" | "templates" | "backup" | "graph";

export default function HomeScreen({
  page = "main",
  onNavigate,
  more,
}: {
  page?: HomePage;
  onNavigate: (target: string) => void;
  // « Pour aller plus loin », fourni par l'application : rendu sous les réglages, avant le lexique.
  more?: ReactNode;
}) {
  const { t } = useI18n();
  const [version, setVersion] = useState(0); // relit les réglages après un enregistrement
  const changed = () => setVersion((count) => count + 1);
  // Lu une fois : ensuite la section s'ouvre au clic ou par `reveal`, sans que React la referme.
  const [detailsOpen] = useState(savedDetails);

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
  // Ma maison en phrases d'abord ; les réglages sont repliés dessous, et un clic sur une phrase
  // les déplie jusqu'au bon réglage. « Ajouter un appareil » ouvre « Appareils et capteurs ».
  return (
    <>
      <HomeSummary
        version={version}
        onOpen={(anchor) => (anchor === "add-device" ? onNavigate("devices#add-device") : void reveal(anchor))}
      />
      <details
        className="plan-more home-details"
        open={detailsOpen}
        onToggle={(event) => rememberDetails(event.currentTarget.open)}
      >
        <summary>{t("home_summary.details")}</summary>
        <ConfigurationSection version={version} onNavigate={onNavigate} />
      </details>
      {more}
      <Glossary />
    </>
  );
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
