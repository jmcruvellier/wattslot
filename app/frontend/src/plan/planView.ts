// Vue du plan ouverte, commune aux sections Planning et Courbes : onglets Hier, Aujourd'hui,
// Demain et Semaine, dernier onglet gardé dans le navigateur (partagé par les deux sections),
// actualisation quand un nouveau calcul arrive, et disposition des cartes de l'installation.

import { useEffect, useState } from "react";

import { ApiError, getJson, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { type DashboardLayout, DEFAULT_LAYOUT } from "./layout";
import type { DayView, Versions, ViewKind, WeekView } from "./types";

export const TABS: ViewKind[] = ["yesterday", "today", "tomorrow", "week"];
export const POLL_MS = 30_000;
const LAYOUT_URL = "api/settings/dashboard";
// Dernière vue ouverte : un confort propre au navigateur (point n° 4).
export const TAB_KEY = "plan.tab";

function savedTab(): ViewKind {
  try {
    const found = window.localStorage.getItem(TAB_KEY);
    return TABS.includes(found as ViewKind) ? (found as ViewKind) : "today";
  } catch {
    return "today";
  }
}

function rememberTab(kind: ViewKind) {
  try {
    window.localStorage.setItem(TAB_KEY, kind);
  } catch {
    // stockage indisponible (navigation privée) : rien à garder
  }
}

export type Load =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error" }
  | { status: "day"; view: DayView }
  | { status: "week"; view: WeekView };

/** « Calculer » ou « Rafraîchir » a réussi (barre de titre) : les vues et les indicateurs se
 * relisent tout de suite, sans attendre leur prochain passage (30 s ou 1 min). */
export const RUN_EVENT = "wattslot:run";

/** Onglet ouvert et sa vue, relue quand un nouveau calcul arrive ou sur `reload`. */
export function usePlanView() {
  const { language } = useI18n();
  const [tab, setTab] = useState<ViewKind>(savedTab);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [version, setVersion] = useState<number | null>(null);
  const [count, setCount] = useState(0); // après « Calculer » ou « Réessayer »
  // « Calculer » ou « Rafraîchir » réussi dans la barre de titre : relecture immédiate.
  useEffect(() => {
    const onRun = () => setCount((value) => value + 1);
    window.addEventListener(RUN_EVENT, onRun);
    return () => window.removeEventListener(RUN_EVENT, onRun);
  }, []);

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
  }, [tab, version, language, count]);

  const open = (kind: ViewKind) => {
    setLoad({ status: "loading" });
    setTab(kind);
    rememberTab(kind);
  };
  const reload = () => setCount((value) => value + 1);
  const retry = () => {
    setLoad({ status: "loading" });
    reload();
  };
  return { tab, load, open, reload, retry };
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

/** Disposition de l'installation (lot 5.5) ; sans réponse, celle par défaut. */
export function useDashboardLayout() {
  const [layout, setLayout] = useState<DashboardLayout>(DEFAULT_LAYOUT);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getJson<DashboardLayout>(LAYOUT_URL, controller.signal)
      .then(setLayout)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const save = async (next: DashboardLayout, request: () => Promise<DashboardLayout>) => {
    const previous = layout;
    setLayout(next);
    setSaving(true);
    setFailed(false);
    try {
      setLayout(await request());
    } catch {
      setLayout(previous);
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const change = (next: DashboardLayout) =>
    void save({ ...next, default: false }, () => putJson<DashboardLayout>(LAYOUT_URL, stored(next)));

  const reset = () =>
    void save(DEFAULT_LAYOUT, async () => {
      const response = await fetch(LAYOUT_URL, { method: "DELETE" });
      if (!response.ok) throw new ApiError(response.status);
      return (await response.json()) as DashboardLayout;
    });

  return { layout, saving, failed, change, reset };
}
