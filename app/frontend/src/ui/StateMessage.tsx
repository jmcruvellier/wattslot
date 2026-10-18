// État d'un écran (lot 6b.7) : chargement, rien à afficher, ou erreur, dit en clair. Une erreur
// dit quoi faire et propose « Réessayer ». Annoncé aux lecteurs d'écran : poliment pendant le
// chargement, tout de suite pour une erreur.

import type { ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import Button from "./Button";
import Icon from "./Icon";

interface StateMessageProps {
  kind: "loading" | "empty" | "error";
  title: string;
  hint?: ReactNode; // erreur : le conseil commun par défaut
  onRetry?: () => void;
}

export default function StateMessage({ kind, title, hint, onRetry }: StateMessageProps) {
  const { t } = useI18n();
  if (kind === "loading") {
    return (
      <p className="state-message state-loading" role="status">
        <span className="state-spinner" aria-hidden="true" />
        {title}
      </p>
    );
  }
  const error = kind === "error";
  return (
    <div className={`state-message state-${kind}`} role={error ? "alert" : "status"}>
      <Icon name={error ? "warning" : "info"} size={22} />
      <div>
        <p className="state-title">{title}</p>
        {(hint ?? (error ? t("state.error_hint") : null)) && (
          <p className="state-hint">{hint ?? t("state.error_hint")}</p>
        )}
        {onRetry && (
          <Button icon="refresh" onClick={onRetry}>
            {t("state.retry")}
          </Button>
        )}
      </div>
    </div>
  );
}
