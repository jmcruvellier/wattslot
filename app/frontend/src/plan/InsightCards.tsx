// Indicateurs du plan, mis en avant selon l'objectif du calcul (point n° 5 de la phase 5), et
// explications de chaque équipement avec la recommandation du jour (lot 5.3). Les textes sont
// rédigés par le serveur dans la langue demandée. Au coin des indicateurs, la qualité des
// prévisions (QualityBadge).

import { useCurrency } from "../i18n/currency";
import { minuteOfDay } from "../i18n/homeTime";
import { useI18n } from "../i18n/I18nProvider";
import { kwh, percent } from "./format";
import { availableIndicators, type IndicatorLayout } from "./layout";
import type { DayView, Indicators, ObjectivePreset } from "./types";
import Icon from "../ui/Icon";
import OtherStarts from "./OtherStarts";
import { QualityBadge } from "./QualityBadge";

// Version compacte (Aujourd'hui, Planning) : libellés courts ; les quatre premières lignes sur
// Aujourd'hui, toutes dans Planning.
const COMPACT_ROWS = 4;
const SHORT_LABELS: IndicatorKey[] = ["cost_eur", "export_kwh"];

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

export function IndicatorsCard({
  view,
  layout,
  compact = false,
  all = false,
}: {
  view: DayView;
  layout: IndicatorLayout;
  compact?: boolean; // panneau à petit titre : quatre lignes, libellés courts, sans phrase
  all?: boolean; // compact : toutes les lignes (Planning)
}) {
  const { t } = useI18n();
  const { money } = useCurrency();
  const indicators = view.indicators;
  // Celui choisi dans la disposition, sinon celui de l'objectif du calcul.
  const main = layout.highlight ?? HIGHLIGHT[view.objective];
  const keys = availableIndicators(view).filter((key) => !layout.hidden.includes(key));
  // L'indicateur visé d'abord.
  const sorted = main && keys.includes(main) ? [main, ...keys.filter((key) => key !== main)] : keys;
  if (!indicators) return null;
  const rows = compact && !all ? sorted.slice(0, COMPACT_ROWS) : sorted;
  return (
    <article className={compact ? "ui-card ui-panel" : "card"} aria-label={t("plan.indicators.title")}>
      {/* Qualité des prévisions au coin droit, comme la tendance des cartes de la vue Aujourd'hui. */}
      <div className={compact ? "ui-panel-head" : "card-head"}>
        <h3 className={compact ? "ui-panel-title" : undefined}>
          <Icon name="target" size={compact ? 16 : 20} /> {t("plan.indicators.title")}
        </h3>
        {view.forecast_quality && <QualityBadge quality={view.forecast_quality} />}
      </div>
      {!compact && (
        <p className="dim">
          {layout.highlight
            ? t("plan.indicators.chosen")
            : t("plan.indicators.goal", { goal: t(`objective.presets.${view.objective}`) })}
        </p>
      )}
      <dl className="indicators">
        {rows.map((key) => (
          <div
            key={key}
            className={key !== main ? "indicator" : compact ? "indicator indicator-strong" : "indicator indicator-main"}
          >
            <dt>{t(compact && SHORT_LABELS.includes(key) ? `plan.indicators.short.${key}` : `plan.indicators.${key}`)}</dt>
            <dd>
              {value(key, indicators, money)}
              {!compact && key === "cost_eur" && (indicators.subscription_eur ?? 0) > 0 && (
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
  const nowMin = minuteOfDay();
  const choosable = view.kind === "today" && onChanged !== undefined;
  return (
    <article className="card" aria-label={t("plan.explanations.title")}>
      <h3>
        <Icon name="bulb" size={20} /> {t("plan.explanations.title")}
      </h3>
      {view.explanations.length > 0 && (
        <ul className="explanations">
          {view.explanations.map((item, index) => (
            // Un équipement peut avoir plusieurs cycles dans la journée : la clé porte son rang.
            <li key={`${item.device}-${index}`}>
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
