// Indicateurs du plan, mis en avant selon l'objectif du calcul (point n° 5 de la phase 5), et
// explications de chaque équipement avec la recommandation du jour (lot 5.3). Les textes sont
// rédigés par le serveur dans la langue demandée.

import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { kwh, percent } from "./format";
import { availableIndicators, type IndicatorLayout } from "./layout";
import type { DayView, Indicators, ObjectivePreset } from "./types";
import Icon from "../ui/Icon";
import OtherStarts from "./OtherStarts";

type IndicatorKey = keyof Indicators;

// Indicateur que vise chaque objectif ; les poids libres n'en mettent aucun en avant.
const HIGHLIGHT: Partial<Record<ObjectivePreset, IndicatorKey>> = {
  cost: "cost_eur",
  autonomy: "import_kwh",
  self_consumption: "self_consumption_percent",
  co2: "co2_kg",
};

// Espace insécable : une valeur ne se sépare pas de son unité.
function value(key: IndicatorKey, indicators: Indicators, money: (value: number) => string): string {
  const raw = indicators[key];
  if (key === "cost_eur") return money(raw ?? 0);
  if (key === "co2_kg") return `${kwh(raw)}\u00a0kg`;
  if (key.endsWith("_percent")) return `${percent(raw)}\u00a0%`;
  return `${kwh(raw)}\u00a0kWh`;
}

export function IndicatorsCard({ view, layout }: { view: DayView; layout: IndicatorLayout }) {
  const { t } = useI18n();
  const { money } = useCurrency();
  const indicators = view.indicators;
  if (!indicators) return null;
  // Celui choisi dans la disposition, sinon celui de l'objectif du calcul.
  const main = layout.highlight ?? HIGHLIGHT[view.objective];
  const keys = availableIndicators(view).filter((key) => !layout.hidden.includes(key));
  // L'indicateur visé d'abord.
  const sorted = main && keys.includes(main) ? [main, ...keys.filter((key) => key !== main)] : keys;
  return (
    <article className="card" aria-label={t("plan.indicators.title")}>
      <h3>
        <Icon name="target" size={20} /> {t("plan.indicators.title")}
      </h3>
      <p className="dim">
        {layout.highlight
          ? t("plan.indicators.chosen")
          : t("plan.indicators.goal", { goal: t(`objective.presets.${view.objective}`) })}
      </p>
      <dl className="indicators">
        {sorted.map((key) => (
          <div key={key} className={key === main ? "indicator indicator-main" : "indicator"}>
            <dt>{t(`plan.indicators.${key}`)}</dt>
            <dd>
              {value(key, indicators, money)}
              {key === "cost_eur" && (indicators.subscription_eur ?? 0) > 0 && (
                <small className="dim">
                  {" "}
                  {t("plan.indicators.subscription_part", { amount: money(indicators.subscription_eur ?? 0) })}
                </small>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

/** « Pourquoi ce plan » ; aujourd'hui, avec ``onChanged``, les autres départs encore à venir de
 * chaque cycle se choisissent ici. */
export function ExplanationsCard({ view, onChanged }: { view: DayView; onChanged?: () => void }) {
  const { t } = useI18n();
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const choosable = view.kind === "today" && onChanged !== undefined;
  return (
    <article className="card" aria-label={t("plan.explanations.title")}>
      <h3>
        <Icon name="bulb" size={20} /> {t("plan.explanations.title")}
      </h3>
      {view.explanations.length > 0 && (
        <ul className="explanations">
          {view.explanations.map((item) => (
            <li key={item.device}>
              <strong>{item.device}</strong> {item.text}
              {choosable && (
                <OtherStarts
                  device={item.device}
                  alternatives={(item.explanation?.alternatives ?? [])
                    .filter((other) => other.debut_min > nowMin)
                    .map((other) => ({
                      start_min: other.debut_min,
                      cost_eur_delta: other.ecart_cout_eur,
                      import_kwh_delta: other.ecart_soutirage_kwh,
                    }))}
                  chosen={item.explanation?.choisi ?? false}
                  onChanged={onChanged}
                />
              )}
            </li>
          ))}
        </ul>
      )}
      {view.recommendation && (
        <details>
          <summary>{t("plan.explanations.recommendation")}</summary>
          <p className="recommendation">{view.recommendation}</p>
        </details>
      )}
    </article>
  );
}
