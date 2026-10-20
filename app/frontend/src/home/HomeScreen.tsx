import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";

import { ApiError, getJson, putJson } from "../api";
import Glossary from "../common/Glossary";
import { useI18n } from "../i18n/I18nProvider";
import Sheet from "../ui/Sheet";
import StateMessage from "../ui/StateMessage";
import Button from "../ui/Button";
import AddDevice from "./AddDevice";
import BatteryEditor from "./BatteryEditor";
import type { Configuration, DeviceSettings as DeviceSettingsType, TaskRules } from "./configuration";
import DeviceSheet from "./DeviceSheet";
import { buildDraft, loadHome, toModel, type DraftDevice, type LoadResult } from "./draft";
import ExchangeSection from "./ExchangeSection";
import HomeEditor from "./HomeEditor";
import { Devices, Essentials, type Essential, type HomeData } from "./HomeSummary";
import ObjectiveEditor from "./ObjectiveEditor";
import PanelsEditor from "./PanelsEditor";
import SettingsSheet from "./SettingsSheet";
import TariffEditor from "./TariffEditor";
import TemplateSection from "./TemplateSection";
import type { HomeModel } from "./types";

// Vue en graphe : React Flow n'est chargé que si on la demande (lot 2t.3).
const HomeGraph = lazy(() => import("./HomeGraph"));
// Onglet « Données » (qualité des données), chargé à son ouverture.
const DataTab = lazy(() => import("./DataTab"));

// Onglet ouvert de la page principale, gardé dans le navigateur comme celui de Planning.
export const TAB_KEY = "home.tab";
const TABS = ["essentials", "devices", "data", "more"] as const;
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
export type HomePage = "main" | "templates" | "backup" | "graph";

export default function HomeScreen({
  page = "main",
  more,
  anchor = null,
  onAnchor,
}: {
  page?: HomePage;
  onNavigate?: (target: string) => void; // gardé pour l'application ; les liens passent par `anchor`
  // Liens des écrans experts, fournis par l'application : rendus dans l'onglet « Avancé ».
  more?: ReactNode;
  // Réglage demandé par un lien (« home#tariff », « home#settings-washer ») : sa feuille s'ouvre.
  anchor?: string | null;
  onAnchor?: () => void;
}) {
  const { t } = useI18n();
  const [version, setVersion] = useState(0); // relit les réglages après un enregistrement
  const changed = () => setVersion((count) => count + 1);

  if (page === "templates") return <TemplateSection version={version} onApplied={changed} />;
  if (page === "backup") return <ExchangeSection onImported={changed} />;
  if (page === "graph") {
    return (
      <Suspense fallback={<p>{t("graph.loading")}</p>}>
        <HomeGraph />
      </Suspense>
    );
  }
  return <HomeMain more={more} anchor={anchor} onAnchor={onAnchor} />;
}

type MainLoad = { status: "loading" } | { status: "error" } | ({ status: "ready" } & HomeData);

// Feuille ouverte : un réglage de « L'essentiel », la fiche d'un appareil ou l'ajout d'un appareil.
type Open = { kind: Essential } | { kind: "device"; key: string } | { kind: "add" };

const ESSENTIALS: readonly string[] = ["objective", "tariff", "solar", "battery"];

// Ancre d'un lien : la feuille qu'elle ouvre, et son onglet.
function anchorSheet(anchor: string): [Tab, Open] | null {
  if (ESSENTIALS.includes(anchor)) return ["essentials", { kind: anchor as Essential }];
  if (anchor === "add-device") return ["devices", { kind: "add" }];
  for (const prefix of ["settings-", "device-"]) {
    if (anchor.startsWith(prefix)) return ["devices", { kind: "device", key: anchor.slice(prefix.length) }];
  }
  return null;
}

// Reprise des règles des tâches de HA : enregistrées, aucune, HA absent, échec.
type RulesState = "idle" | "loading" | "applied" | "none" | "not_connected" | "failed";

// Appareils de la maison enregistrée, sans les propositions de HA (HA absent) : la fiche garde
// leurs capteurs, sans points à vérifier.
function savedDraft(home: HomeModel): DraftDevice[] {
  return buildDraft([], home).map((device) => ({ ...device, issues: [] }));
}

// Page principale (refonte de Ma maison) : trois onglets courts, et chaque réglage ou appareil dans
// sa feuille, enregistré seul. Rien n'est déplié d'avance : une ligne par réglage ou par appareil.
function HomeMain({
  more,
  anchor,
  onAnchor,
}: {
  more?: ReactNode;
  anchor: string | null;
  onAnchor?: () => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>(savedTab);
  const [load, setLoad] = useState<MainLoad>({ status: "loading" });
  // Propositions de HA (capteurs, points à vérifier, appareils pas encore suivis) : lues à côté,
  // la page ne les attend pas.
  const [found, setFound] = useState<LoadResult | null>(null);
  const [attempt, setAttempt] = useState(0); // « Réessayer », et relecture après un enregistrement
  const [open, setOpen] = useState<Open | null>(null);
  const [saved, setSaved] = useState(false);
  const [rules, setRules] = useState<RulesState>("idle");
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<HomeModel>("api/home", controller.signal),
      getJson<Configuration>("api/configuration", controller.signal),
    ])
      .then(([home, configuration]) => {
        setLoad({ status: "ready", devices: home.devices, configuration });
        // Maison pas encore enregistrée : on commence par ses appareils.
        if (home.devices.length === 0) setTab("devices");
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    let cancelled = false;
    loadHome(false).then((result) => {
      if (!cancelled) setFound(result);
    });
    return () => {
      controller.abort();
      cancelled = true;
    };
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
    const target = anchorSheet(anchor);
    if (target) {
      setTab(target[0]);
      setOpen(target[1]);
    }
  }
  useEffect(() => {
    if (anchor && anchor === handled) onAnchor?.();
  }, [anchor, handled, onAnchor]);

  const data: HomeData | null =
    load.status === "ready" ? { devices: load.devices, configuration: load.configuration } : null;
  const names = new Map(data?.devices.map((device) => [device.key, device.name]));
  const firstSave = data !== null && data.devices.length === 0;
  // Appareils de la fiche : propositions de HA fusionnées avec la maison, sinon la maison seule.
  const draft = found?.ok ? found.draft : data ? savedDraft({ devices: data.devices }) : [];

  const show = (next: Open) => {
    setSaved(false);
    setOpen(next);
  };

  const done = () => {
    setOpen(null);
    setSaved(true);
  };

  // Enregistrement qui touche la maison : tout est relu (appareils, réglages, propositions).
  const reload = () => {
    done();
    setAttempt((count) => count + 1);
  };

  const onSettingsSaved = (configuration: Configuration) => {
    if (data) setLoad({ status: "ready", ...data, configuration });
    done();
  };

  const onRefresh = async () => {
    setRefreshing(true);
    setFound(await loadHome(true));
    setRefreshing(false);
  };

  // Reprise des règles des descriptions JSON des tâches de HA (lot 3.5), enregistrées aussitôt :
  // chaque appareil concerné les montre ensuite dans sa fiche.
  const onImportRules = async (current: HomeData) => {
    setRules("loading");
    try {
      const proposals = await getJson<TaskRules[]>("api/configuration/task-rules-proposal");
      const byDevice = new Map(proposals.map((r) => [r.key, r]));
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

  const device = open?.kind === "device" ? draft.find((d) => d.key === open.key) : undefined;

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
        {tab === "devices" && data && firstSave && <HomeEditor onSaved={reload} />}
        {tab === "devices" && data && !firstSave && (
          <Devices
            data={data}
            proposed={draft.filter((d) => !d.included).map((d) => ({ key: d.key, name: d.name }))}
            onOpen={(key) => show({ kind: "device", key })}
            onAdd={() => show({ kind: "add" })}
            onRefresh={found?.ok ? () => void onRefresh() : undefined}
            refreshing={refreshing}
          />
        )}
        {tab === "data" && data && !firstSave && (
          <Suspense fallback={<StateMessage kind="loading" title={t("quality.loading")} />}>
            <DataTab data={data} />
          </Suspense>
        )}
        {tab === "more" && (
          <>
            {data && !firstSave && (
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
      {open && data && open.kind !== "device" && open.kind !== "add" && (
        <HomeSheet open={open} data={data} names={names} onClose={() => setOpen(null)} onSaved={onSettingsSaved} />
      )}
      {open && data && device && (
        <DeviceSheet
          key={device.key}
          device={device}
          home={draft}
          configuration={data.configuration}
          types={found?.ok ? found.types : []}
          names={names}
          onClose={() => setOpen(null)}
          onSaved={reload}
        />
      )}
      {open?.kind === "add" && (
        <AddSheet found={found} draft={draft} onClose={() => setOpen(null)} onSaved={reload} />
      )}
    </>
  );
}

// Ajout d'un appareil absent du tableau Énergie de HA (lot 2t.2), enregistré aussitôt.
function AddSheet({
  found,
  draft,
  onClose,
  onSaved,
}: {
  found: LoadResult | null;
  draft: DraftDevice[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);
  return (
    <Sheet open wide title={t("home.add.title")} onClose={onClose}>
      <div className="expert-form">
        <AddDevice
          opened
          library={found?.ok ? found.library : []}
          types={found?.ok ? found.types : []}
          existing={draft.map((device) => device.key)}
          onCancel={onClose}
          onAdd={async (device) => {
            setFailed(false);
            try {
              await putJson("api/home", toModel([...draft, device]));
              onSaved();
            } catch {
              setFailed(true);
            }
          }}
        />
      </div>
      {failed && <p role="alert">{t("home.save_failed")}</p>}
    </Sheet>
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
  open: { kind: Essential };
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
  // Panneaux modifiés : ils ne sont plus ceux par défaut de son type.
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
  }
}
