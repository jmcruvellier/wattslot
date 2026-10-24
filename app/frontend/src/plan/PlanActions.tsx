// Actions de la barre de titre des sections Aujourd'hui, Planning et Courbes (App.tsx) :
// « Calculer » et « Rafraîchir les données réelles » en icônes, l'âge du dernier calcul et du
// dernier relevé à côté de chacune (api/planning/last-run), le détail (heure, automatique ou à
// la main) dans l'infobulle et pour les lecteurs d'écran. L'échec passe sous la barre (styles.css).

import { useEffect, useState, type ReactNode } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { refreshStatus } from "../nav/status";
import { since, time } from "./format";
import { setCurvesEditing, useCurvesEditing } from "./curvesEdit";
import { RUN_EVENT } from "./planView";
import Icon from "../ui/Icon";

type Running = "compute" | "refresh" | null;
type LastRun = { computed_at: string | null; manual: boolean; actual_updated_at: string | null };

const LAST_RUN_URL = "api/planning/last-run";
// Âge affiché à côté des icônes, rafraîchi sans relire le serveur.
const TICK_MS = 30_000;

/** Dernier calcul et dernier relevé, relus périodiquement, après une action et après le calcul
 * d'un autre navigateur (`api/views/versions` fait de même pour les vues). */
function useLastRun(): LastRun | null {
  const [last, setLast] = useState<LastRun | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const read = () =>
      getJson<LastRun>(LAST_RUN_URL, controller.signal)
        .then(setLast)
        .catch(() => undefined);
    void read();
    const timer = window.setInterval(() => void read(), TICK_MS);
    window.addEventListener(RUN_EVENT, read);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener(RUN_EVENT, read);
    };
  }, []);
  return last;
}

/** Rejoue le rendu toutes les 30 s : « il y a 12 min » devient « il y a 13 min ». */
function useTick(): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((count) => count + 1), TICK_MS);
    return () => window.clearInterval(timer);
  }, []);
}

export default function PlanActions({ leading }: { leading?: ReactNode }) {
  const { language, t } = useI18n();
  // Seul le bouton lancé est animé ; l'autre garde son âge affiché, sans tourner (styles.css).
  const [running, setRunning] = useState<Running>(null);
  const [failed, setFailed] = useState(false);
  const last = useLastRun();
  useTick();

  const run = async (action: Exclude<Running, null>, url: string) => {
    setRunning(action);
    try {
      const response = await fetch(url, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      // Les vues ouvertes se relisent tout de suite (planView, TodayView).
      window.dispatchEvent(new Event(RUN_EVENT));
    } catch {
      setFailed(true);
    }
    setRunning(null);
    refreshStatus();
  };

  // Le détail de chaque action : libellé, puis dernière exécution (« Calculé à 14:59 (auto) »).
  const how = t(last?.manual ? "plan.header.manual" : "plan.header.auto");
  const computed = last?.computed_at
    ? t("plan.header.computed", { time: time(last.computed_at, language), how })
    : t("plan.header.never");
  const reading = last?.actual_updated_at
    ? t("plan.header.reading", { time: time(last.actual_updated_at, language) })
    : null;
  const computeLabel = `${t("plan.header.compute")} — ${computed}`;
  const refreshLabel = `${t("plan.header.refresh")}${reading ? ` — ${reading}` : ""}`;

  return (
    <>
      <div className="run-actions">
        {/* Icône à gauche des deux actions (section Courbes : « Personnaliser »). */}
        {leading}
        <button
          type="button"
          className={running === "compute" ? "run-button run-button-primary run-button-running" : "run-button run-button-primary"}
          disabled={running !== null}
          onClick={() => void run("compute", "api/planning/run")}
          title={computeLabel}
          aria-label={computeLabel}
        >
          <Icon name="play" size={18} />
          <span className="run-when" aria-hidden="true">
            {last?.computed_at ? since(last.computed_at, language) : "—"}
          </span>
        </button>
        <button
          type="button"
          className={running === "refresh" ? "run-button run-button-running" : "run-button"}
          disabled={running !== null}
          onClick={() => void run("refresh", "api/planning/actual")}
          title={refreshLabel}
          aria-label={refreshLabel}
        >
          <Icon name="refresh" size={18} />
          <span className="run-when" aria-hidden="true">
            {last?.actual_updated_at ? since(last.actual_updated_at, language) : "—"}
          </span>
        </button>
      </div>
      {failed && <p role="alert">{t("plan.header.failed")}</p>}
    </>
  );
}

/** « Personnaliser » (section Courbes) en icône, dans la barre de titre, à gauche de « Calculer »
 * et « Rafraîchir » (même style de pilule, sans l'âge d'une exécution) ; le panneau s'ouvre dans
 * l'écran (`CurvesScreen`, via curvesEdit) ; le nom complet reste au lecteur d'écran. */
export function CurvesCustomizeButton() {
  const { t } = useI18n();
  const { editing, available } = useCurvesEditing();
  if (!available) return null;
  return (
    <button
      type="button"
      className="run-button run-button-icon"
      aria-pressed={editing}
      title={t("plan.layout.open")}
      aria-label={t("plan.layout.open")}
      onClick={() => setCurvesEditing(!editing)}
    >
      <Icon name="layout" size={18} />
    </button>
  );
}
