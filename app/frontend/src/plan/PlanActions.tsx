// Actions de la barre de titre des sections Aujourd'hui, Planning et Courbes (App.tsx) :
// « Calculer » et « Rafraîchir les données réelles » en icônes, l'âge du dernier calcul et du
// dernier relevé à côté de chacune (api/planning/last-run), le détail (heure, automatique ou à
// la main) dans l'infobulle et pour les lecteurs d'écran. L'échec passe sous la barre (styles.css).

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { refreshStatus } from "../nav/status";
import { since, time } from "./format";
import { RUN_EVENT } from "./planView";
import Icon from "../ui/Icon";

type Action = "idle" | "running" | "failed";
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

export default function PlanActions() {
  const { language, t } = useI18n();
  const [action, setAction] = useState<Action>("idle");
  const last = useLastRun();
  useTick();

  const run = async (url: string) => {
    setAction("running");
    try {
      const response = await fetch(url, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setAction("idle");
      // Les vues ouvertes se relisent tout de suite (planView, TodayView).
      window.dispatchEvent(new Event(RUN_EVENT));
    } catch {
      setAction("failed");
    }
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
  const running = action === "running";

  return (
    <>
      <div className="run-actions">
        <button
          type="button"
          className="run-button run-button-primary"
          disabled={running}
          onClick={() => void run("api/planning/run")}
          title={computeLabel}
          aria-label={computeLabel}
        >
          <Icon name="play" size={18} />
          <span className="run-when" aria-hidden="true">
            {running ? "…" : last?.computed_at ? since(last.computed_at, language) : "—"}
          </span>
        </button>
        <button
          type="button"
          className="run-button"
          disabled={running}
          onClick={() => void run("api/planning/actual")}
          title={refreshLabel}
          aria-label={refreshLabel}
        >
          <Icon name="refresh" size={18} />
          <span className="run-when" aria-hidden="true">
            {running ? "…" : last?.actual_updated_at ? since(last.actual_updated_at, language) : "—"}
          </span>
        </button>
      </div>
      {action === "failed" && (
        <p role="alert">
          {t("plan.header.failed")}
        </p>
      )}
    </>
  );
}
