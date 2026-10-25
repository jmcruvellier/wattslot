// Mesure impossible écartée (qualité des données, lot qualité 3/3) : une ligne au-dessus des
// cartes. Chaque vue ne reçoit que les heures écartées de sa propre plage — Aujourd'hui celles
// du jour, Hier celles de la veille, Semaine celles du jour qui ouvre la semaine ; une mesure
// plus ancienne n'apparaît nulle part. « Voir les données » ouvre Ma maison sur l'onglet Données.

import { useI18n } from "../i18n/I18nProvider";
import { rememberTab } from "../home/tab";

export default function DiscardedNote({ hours }: { hours: number[] }) {
  const { t } = useI18n();
  if (hours.length === 0) return null;
  return (
    <p className="card discarded-note" role="note">
      {t("plan.discarded", { hours: hours.map((hour) => `${hour} h`).join(", ") })}{" "}
      <a href="#/home" onClick={() => rememberTab("data")}>
        {t("plan.discarded_link")}
      </a>
    </p>
  );
}
