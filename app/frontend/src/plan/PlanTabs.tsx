// Onglets et messages d'état des sections Planning et Courbes, autour de `usePlanView`.

import { useEffect, useRef } from "react";

import { useI18n } from "../i18n/I18nProvider";
import StateMessage from "../ui/StateMessage";
import { type Load, TABS } from "./planView";
import type { ViewKind } from "./types";

/** Onglets des vues, sous le titre (caché) de la section ; sur un écran étroit, la ligne défile
 * jusqu'à l'onglet ouvert. */
export function PlanTabs({ title, tab, onOpen }: { title: string; tab: ViewKind; onOpen: (kind: ViewKind) => void }) {
  const { t } = useI18n();
  const selected = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    selected.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [tab]);
  return (
    <div className="view-tabs" role="tablist" aria-label={title}>
      {TABS.map((kind) => (
        <button
          key={kind}
          ref={tab === kind ? selected : undefined}
          type="button"
          role="tab"
          aria-selected={tab === kind}
          onClick={() => onOpen(kind)}
        >
          {t(`plan.tabs.${kind}`)}
        </button>
      ))}
    </div>
  );
}

/** Chargement, plan absent ou erreur ; rien une fois la vue lue. */
export function LoadMessage({ load, tab, onRetry }: { load: Load; tab: ViewKind; onRetry: () => void }) {
  const { t } = useI18n();
  if (load.status === "loading") return <StateMessage kind="loading" title={t("plan.loading")} />;
  if (load.status === "missing") {
    return (
      <StateMessage
        kind="empty"
        title={t(tab === "yesterday" ? "plan.missing_yesterday" : tab === "week" ? "plan.missing_week" : "plan.missing")}
      />
    );
  }
  if (load.status === "error") return <StateMessage kind="error" title={t("plan.error")} onRetry={onRetry} />;
  return null;
}
