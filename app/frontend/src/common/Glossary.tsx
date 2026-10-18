// Lexique minimal (lot 4.7) : les quelques mots de l'énergie que l'application emploie, replié en
// bas de l'accueil et de « Ma maison ».

import { useI18n } from "../i18n/I18nProvider";

const TERMS = [
  "grid_import",
  "surplus",
  "self_consumption",
  "autonomy",
  "off_peak",
  "kwh",
  "kwp",
  "cycle",
  "floor",
  "energy_dashboard",
  "sensor",
] as const;

export default function Glossary() {
  const { t } = useI18n();
  return (
    <details>
      <summary>{t("glossary.title")}</summary>
      <dl>
        {TERMS.map((term) => (
          <div key={term}>
            <dt>{t(`glossary.terms.${term}.term`)}</dt>
            <dd>{t(`glossary.terms.${term}.definition`)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
