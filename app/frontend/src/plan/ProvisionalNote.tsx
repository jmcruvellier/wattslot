// Plan provisoire (essai d'installation du 21/10/2026) : calculé pendant la reprise de
// l'historique de Home Assistant, sans la consommation habituelle ni toutes les mesures du jour.
// Ses chiffres (surplus, achats…) se précisent au premier calcul après la reprise.

import { useI18n } from "../i18n/I18nProvider";
import type { DayView } from "./types";

export default function ProvisionalNote({ view }: { view: DayView }) {
  const { t } = useI18n();
  if (!view.history_pending) return null;
  return (
    <p className="card discarded-note" role="note">
      {t("plan.provisional", { count: view.history_pending })}
    </p>
  );
}
