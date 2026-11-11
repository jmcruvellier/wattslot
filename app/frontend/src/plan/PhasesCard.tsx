// Carte « Par phase » du jour (triphasé) : ce que chaque phase achète et vend au réseau sur la
// journée, prévu par le plan et, s'il y a des capteurs par phase, mesuré jusqu'ici. Absente quand
// le plan n'a pas été calculé par phase.

import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n/translate";
import Card from "../ui/Card";
import type { DayView } from "./types";

export default function PhasesCard({ view }: { view: DayView }) {
  const { language, t } = useI18n();
  const phases = view.phases ?? [];
  if (phases.length === 0) return null;
  const measured = phases.some((phase) => phase.import_actual_kwh != null || phase.export_actual_kwh != null);
  const kwh = (value: number | null | undefined) =>
    value == null ? "—" : `${formatNumber(language, value, 1)} kWh`;

  return (
    <Card title={t("phases.title")}>
      <p className="dim">{t("phases.note")}</p>
      <table className="phases-table">
        <thead>
          <tr>
            <td />
            <th scope="col">{t("phases.import")}</th>
            <th scope="col">{t("phases.export")}</th>
            {measured && <th scope="col">{t("phases.import_actual")}</th>}
            {measured && <th scope="col">{t("phases.export_actual")}</th>}
          </tr>
        </thead>
        <tbody>
          {phases.map((phase) => (
            <tr key={phase.phase}>
              <th scope="row">{t("phases.phase", { number: phase.phase })}</th>
              <td>{kwh(phase.import_kwh)}</td>
              <td>{kwh(phase.export_kwh)}</td>
              {measured && <td>{kwh(phase.import_actual_kwh)}</td>}
              {measured && <td>{kwh(phase.export_actual_kwh)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
