// « Plan du jour », nouveau dashboard (lot 5.2, socle) : onglets Hier, Aujourd'hui, Demain et
// Semaine sur l'API des vues, actualisation quand un nouveau calcul arrive. Section Planning
// (lot 6b.4) : chaque jour en agenda (`Agenda`), « Pourquoi ce plan » et « Courbes détaillées »
// (les cartes de la phase 5) repliés par défaut.
// Cartes des jours : lot 5.3 (`DayCards`) ; disposition gardée dans l'installation et panneau
// « Personnaliser » : lot 5.5. L'ancien dashboard reste accessible jusqu'au lot 5.8.

import { type SyntheticEvent, useEffect, useState } from "react";

import { ApiError, getJson, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import Agenda, { DaySummaryCard } from "./Agenda";
import Banners from "./Banners";
import DayCards from "./DayCards";
import { ExplanationsCard } from "./InsightCards";
import { availableIndicators, availableDayCards, availableWeekCards, type DashboardLayout, DEFAULT_LAYOUT } from "./layout";
import LayoutEditor from "./LayoutEditor";
import type { DayView, Versions, ViewKind, WeekView } from "./types";
import ViewHeader from "./ViewHeader";
import WeekScreen, { WeekDetails } from "./WeekScreen";
import StateMessage from "../ui/StateMessage";

const TABS: ViewKind[] = ["yesterday", "today", "tomorrow", "week"];
export const POLL_MS = 30_000;
const LAYOUT_URL = "api/settings/dashboard";
// Dernière vue ouverte : un confort propre au navigateur (point n° 4).
const TAB_KEY = "plan.tab";

function savedTab(): ViewKind {
  try {
    const found = window.localStorage.getItem(TAB_KEY);
    return TABS.includes(found as ViewKind) ? (found as ViewKind) : "today";
  } catch {
    return "today";
  }
}

// « Courbes détaillées » ouvertes ou repliées (lot 6b.4), gardé comme l'onglet.
export const CURVES_KEY = "plan.curves";

function savedCurves(): boolean {
  try {
    return window.localStorage.getItem(CURVES_KEY) === "open";
  } catch {
    return false;
  }
}

function rememberCurves(open: boolean) {
  try {
    window.localStorage.setItem(CURVES_KEY, open ? "open" : "closed");
  } catch {
    // stockage indisponible : rien à garder
  }
}

function rememberTab(kind: ViewKind) {
  try {
    window.localStorage.setItem(TAB_KEY, kind);
  } catch {
    // stockage indisponible (navigation privée) : rien à garder
  }
}

/** Disposition envoyée au serveur : sans l'indication « par défaut », qu'il calcule. */
function stored(layout: DashboardLayout): Omit<DashboardLayout, "default"> {
  return {
    yesterday: layout.yesterday,
    today: layout.today,
    tomorrow: layout.tomorrow,
    week: layout.week,
    indicators: layout.indicators,
  };
}

type Load =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error" }
  | { status: "day"; view: DayView }
  | { status: "week"; view: WeekView };

export default function PlanScreen() {
  const { language, t } = useI18n();
  const [tab, setTab] = useState<ViewKind>(savedTab);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [version, setVersion] = useState<number | null>(null);
  const [reload, setReload] = useState(0); // après « Calculer » ou « Rafraîchir »
  const [layout, setLayout] = useState<DashboardLayout>(DEFAULT_LAYOUT);
  const [editing, setEditing] = useState(false);
  const [curves, setCurves] = useState(savedCurves); // « Courbes détaillées » ouvertes
  const [saving, setSaving] = useState(false);
  const [layoutFailed, setLayoutFailed] = useState(false);
  // Disposition de l'installation ; sans réponse, celle par défaut.
  useEffect(() => {
    const controller = new AbortController();
    getJson<DashboardLayout>(LAYOUT_URL, controller.signal)
      .then(setLayout)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const saveLayout = async (next: DashboardLayout, request: () => Promise<DashboardLayout>) => {
    const previous = layout;
    setLayout(next);
    setSaving(true);
    setLayoutFailed(false);
    try {
      setLayout(await request());
    } catch {
      setLayout(previous);
      setLayoutFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const changeLayout = (next: DashboardLayout) =>
    void saveLayout({ ...next, default: false }, () => putJson<DashboardLayout>(LAYOUT_URL, stored(next)));

  const resetLayout = () =>
    void saveLayout(DEFAULT_LAYOUT, async () => {
      const response = await fetch(LAYOUT_URL, { method: "DELETE" });
      if (!response.ok) throw new ApiError(response.status);
      return (await response.json()) as DashboardLayout;
    });

  // Version de la vue affichée, relue régulièrement : un nouveau calcul recharge la vue.
  useEffect(() => {
    let active = true;
    const check = () =>
      getJson<Versions>("api/views/versions")
        .then((versions) => {
          if (active) setVersion(versions[tab]);
        })
        .catch(() => undefined);
    void check();
    const timer = window.setInterval(() => void check(), POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [tab]);

  useEffect(() => {
    const controller = new AbortController();
    const url = `api/views/${tab}?lang=${language}`;
    getJson<DayView | WeekView>(url, controller.signal)
      .then((view) =>
        setLoad(tab === "week" ? { status: "week", view: view as WeekView } : { status: "day", view: view as DayView }),
      )
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setLoad({ status: error instanceof ApiError && error.status === 404 ? "missing" : "error" });
      });
    return () => controller.abort();
  }, [tab, version, language, reload]);

  const toggleCurves = (event: SyntheticEvent<HTMLDetailsElement>) => {
    const opened = event.currentTarget.open;
    setCurves(opened);
    rememberCurves(opened);
  };

  const open = (kind: ViewKind) => {
    setLoad({ status: "loading" });
    setTab(kind);
    rememberTab(kind);
  };

  return (
    <section aria-labelledby="plan-title">
      {/* Le titre de la section est dans la barre du haut (lot 6b.2). */}
      <h2 id="plan-title" className="visually-hidden">
        {t("plan.title")}
      </h2>
      <div className="view-tabs" role="tablist" aria-label={t("plan.title")}>
        {TABS.map((kind) => (
          <button
            key={kind}
            type="button"
            role="tab"
            aria-selected={tab === kind}
            onClick={() => open(kind)}
          >
            {t(`plan.tabs.${kind}`)}
          </button>
        ))}
      </div>

      {load.status === "loading" && <StateMessage kind="loading" title={t("plan.loading")} />}
      {load.status === "missing" && (
        <StateMessage
          kind="empty"
          title={t(tab === "yesterday" ? "plan.missing_yesterday" : tab === "week" ? "plan.missing_week" : "plan.missing")}
        />
      )}
      {load.status === "error" && (
        <StateMessage
          kind="error"
          title={t("plan.error")}
          onRetry={() => {
            setLoad({ status: "loading" });
            setReload((count) => count + 1);
          }}
        />
      )}

      {load.status === "day" && (
        <>
          <ViewHeader view={load.view} onChanged={() => setReload((count) => count + 1)} />
          <Banners view={load.view} />
          <div className="plan-agenda">
            <DaySummaryCard view={load.view} />
            <Agenda view={load.view} />
          </div>
          <details className="plan-more">
            <summary>{t("plan.agenda.why")}</summary>
            <ExplanationsCard view={load.view} />
          </details>
          {/* Rendues seulement une fois ouvertes : les graphiques (Recharts) ne se chargent pas
              tant qu'on ne les demande pas. */}
          <details className="plan-more" open={curves} onToggle={toggleCurves}>
            <summary>{t("plan.agenda.curves")}</summary>
            {curves && (
            <>
            <p>
              <button type="button" aria-pressed={editing} onClick={() => setEditing(!editing)}>
                {t("plan.layout.open")}
              </button>
            </p>
            {editing && (
              <LayoutEditor
                kind={tab}
                layout={layout}
                available={availableDayCards(load.view)}
                indicators={availableIndicators(load.view)}
                saving={saving}
                failed={layoutFailed}
                onChange={changeLayout}
                onReset={resetLayout}
                onClose={() => setEditing(false)}
              />
            )}
            <DayCards view={load.view} layout={layout[load.view.kind]} indicators={layout.indicators} />
            </>
            )}
          </details>
        </>
      )}

      {load.status === "week" && (
        <>
          <WeekScreen view={load.view} onChanged={() => setReload((count) => count + 1)} onOpen={open} />
          <details className="plan-more" open={curves} onToggle={toggleCurves}>
            <summary>{t("plan.agenda.curves")}</summary>
            {curves && (
              <>
                <p>
                  <button type="button" aria-pressed={editing} onClick={() => setEditing(!editing)}>
                    {t("plan.layout.open")}
                  </button>
                </p>
                {editing && (
                  <LayoutEditor
                    kind="week"
                    layout={layout}
                    available={availableWeekCards(load.view)}
                    indicators={[]}
                    saving={saving}
                    failed={layoutFailed}
                    onChange={changeLayout}
                    onReset={resetLayout}
                    onClose={() => setEditing(false)}
                  />
                )}
                <WeekDetails view={load.view} onOpen={open} layout={layout.week} />
              </>
            )}
          </details>
        </>
      )}
    </section>
  );
}
