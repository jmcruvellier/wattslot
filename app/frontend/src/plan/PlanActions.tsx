// Actions de la vue ouverte dans Planning, à droite des onglets : « Calculer » (Aujourd'hui,
// Demain, Semaine) et « Rafraîchir les données réelles » (Aujourd'hui), comme dans la v1 ;
// rien pour Hier. Le message d'échec passe sous la ligne des onglets (styles.css).

import { useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { refreshStatus } from "../nav/status";
import type { ViewKind } from "./types";

type Action = "idle" | "running" | "failed";

export default function PlanActions({ kind, onChanged }: { kind: ViewKind; onChanged: () => void }) {
  const { t } = useI18n();
  const [action, setAction] = useState<Action>("idle");
  if (kind === "yesterday") return null;

  const run = async (url: string) => {
    setAction("running");
    try {
      const response = await fetch(url, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setAction("idle");
      onChanged();
    } catch {
      setAction("failed");
    }
    refreshStatus();
  };

  return (
    <>
      <div className="view-actions">
        <button type="button" disabled={action === "running"} onClick={() => void run("api/planning/run")}>
          {t(action === "running" ? "plan.header.running" : "plan.header.compute")}
        </button>
        {kind === "today" && (
          <button type="button" disabled={action === "running"} onClick={() => void run("api/planning/actual")}>
            {t("plan.header.refresh")}
          </button>
        )}
      </div>
      {action === "failed" && <p role="alert">{t("plan.header.failed")}</p>}
    </>
  );
}
