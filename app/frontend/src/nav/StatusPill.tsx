// Pastille d'état (lot 6b.2) : verte « Tout fonctionne », orange « À vérifier », rouge « Le
// calcul est bloqué » ; un clic ouvre l'état de l'application (diagnostic).

import { useI18n } from "../i18n/I18nProvider";
import { routeHash } from "./routes";
import type { StatusLevel } from "./status";

export default function StatusPill({ level }: { level: StatusLevel | null }) {
  const { t } = useI18n();
  if (level === null) return null;
  const label = t(`nav.status_${level}`);
  return (
    <a className="status-pill" data-level={level} href={routeHash({ section: "settings", sub: "status" })} title={label}>
      <span className="status-dot" aria-hidden="true" />
      <span className="status-label">{label}</span>
    </a>
  );
}
