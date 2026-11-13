// Carte « Par phase » du jour (triphasé) : ce que chaque phase achète et vend au réseau sur la
// journée, prévu par le plan et, s'il y a des capteurs par phase, mesuré jusqu'ici (sous le
// prévu, pour tenir dans une carte étroite). Absente quand le plan n'a pas été calculé par phase,
// sauf si la maison le demande (batterie qui ne compense que sa phase, compteur qui compte chaque
// phase à part) : la carte dit alors ce qui manque, au lieu de laisser croire à un calcul par phase.

import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n/translate";
import Icon from "../ui/Icon";
import type { DayView } from "./types";

export default function PhasesCard({ view }: { view: DayView }) {
  const { language, t } = useI18n();
  const phases = view.phases ?? [];
  const gap = view.now?.phase_gap;
  if (phases.length === 0) {
    if (!gap) return null;
    return (
      <article className="card" aria-label={t("phases.title")}>
        <h3>
          <Icon name="plug" size={20} /> {t("phases.title")}
        </h3>
        <p>{t(`phases.gap.${gap.code}`, gap.params)}</p>
      </article>
    );
  }
  const measured = phases.some((phase) => phase.import_actual_kwh != null || phase.export_actual_kwh != null);
  const kwh = (value: number) => `${formatNumber(language, value, 1)} kWh`;
  const cell = (planned: number, actual: number | null | undefined) => (
    <td>
      {kwh(planned)}
      {measured && (
        <small className="dim">{actual == null ? t("phases.unmeasured") : t("phases.measured", { kwh: kwh(actual) })}</small>
      )}
    </td>
  );

  return (
    <article className="card" aria-label={t("phases.title")}>
      <h3>
        <Icon name="plug" size={20} /> {t("phases.title")}
      </h3>
      <p className="dim">{t(measured ? "phases.note_measured" : "phases.note")}</p>
      <table className="phases-table">
        <thead>
          <tr>
            <td />
            <th scope="col">{t("phases.import")}</th>
            <th scope="col">{t("phases.export")}</th>
          </tr>
        </thead>
        <tbody>
          {phases.map((phase) => (
            <tr key={phase.phase}>
              <th scope="row">{t("phases.phase", { number: phase.phase })}</th>
              {cell(phase.import_kwh, phase.import_actual_kwh)}
              {cell(phase.export_kwh, phase.export_actual_kwh)}
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}
