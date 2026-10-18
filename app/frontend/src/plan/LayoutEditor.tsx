// Panneau « Personnaliser » (lot 5.5) : ordre et cartes masquées de la vue ouverte, indicateur
// mis en avant et indicateurs affichés ; chaque changement est enregistré dans l'installation.
// Des boutons plutôt que le glisser-déposer : ils marchent au doigt et au clavier.

import { useI18n } from "../i18n/I18nProvider";
import {
  type CardId,
  type DashboardLayout,
  hide,
  type IndicatorKey,
  move,
  restore,
  shownCards,
} from "./layout";
import type { ViewKind } from "./types";
import Icon from "../ui/Icon";

export default function LayoutEditor({
  kind,
  layout,
  available,
  indicators,
  saving,
  failed,
  onChange,
  onReset,
  onClose,
}: {
  kind: ViewKind;
  layout: DashboardLayout;
  available: CardId[];
  indicators: IndicatorKey[]; // indicateurs du plan affiché (vues de jour)
  saving: boolean;
  failed: boolean;
  onChange: (layout: DashboardLayout) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const view = layout[kind];
  const shown = shownCards(view, available);
  const hidden = view.order.filter((id) => available.includes(id) && view.hidden.includes(id));
  const label = (id: CardId) => t(`plan.layout.${kind === "week" ? "week" : "day"}.${id}`);
  const update = (next: typeof view) => onChange({ ...layout, [kind]: next });
  const setIndicators = (next: DashboardLayout["indicators"]) => onChange({ ...layout, indicators: next });

  return (
    <section className="card layout-editor" aria-label={t("plan.layout.title")}>
      <h3>
        <Icon name="layout" size={20} /> {t("plan.layout.title")}
      </h3>
      <p className="dim">{t("plan.layout.hint", { view: t(`plan.tabs.${kind}`) })}</p>
      <ol className="layout-cards">
        {shown.map((id, index) => (
          <li key={id}>
            <span>{label(id)}</span>
            <span className="layout-actions">
              <button
                type="button"
                disabled={index === 0}
                aria-label={t("plan.layout.up", { card: label(id) })}
                onClick={() => update(move(view, shown, id, -1))}
              >
                ↑
              </button>
              <button
                type="button"
                disabled={index === shown.length - 1}
                aria-label={t("plan.layout.down", { card: label(id) })}
                onClick={() => update(move(view, shown, id, 1))}
              >
                ↓
              </button>
              <button
                type="button"
                aria-label={t("plan.layout.hide", { card: label(id) })}
                onClick={() => update(hide(view, id))}
              >
                {t("plan.layout.hide_short")}
              </button>
            </span>
          </li>
        ))}
      </ol>
      {hidden.length > 0 && (
        <>
          <h4>{t("plan.layout.hidden")}</h4>
          <ul className="layout-cards">
            {hidden.map((id) => (
              <li key={id}>
                <span className="dim">{label(id)}</span>
                <button
                  type="button"
                  aria-label={t("plan.layout.restore", { card: label(id) })}
                  onClick={() => update(restore(view, id))}
                >
                  {t("plan.layout.restore_short")}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {kind !== "week" && indicators.length > 0 && (
        <fieldset className="layout-indicators">
          <legend>{t("plan.layout.indicators")}</legend>
          <label>
            {t("plan.layout.highlight")}{" "}
            <select
              value={layout.indicators.highlight ?? ""}
              onChange={(event) => {
                const highlight = (event.target.value || null) as IndicatorKey | null;
                setIndicators({
                  highlight,
                  hidden: layout.indicators.hidden.filter((key) => key !== highlight),
                });
              }}
            >
              <option value="">{t("plan.layout.highlight_goal")}</option>
              {indicators.map((key) => (
                <option key={key} value={key}>
                  {t(`plan.indicators.${key}`)}
                </option>
              ))}
            </select>
          </label>
          {indicators.map((key) => (
            <label key={key} className="layout-check">
              <input
                type="checkbox"
                checked={!layout.indicators.hidden.includes(key)}
                disabled={key === layout.indicators.highlight}
                onChange={(event) =>
                  setIndicators({
                    ...layout.indicators,
                    hidden: event.target.checked
                      ? layout.indicators.hidden.filter((hiddenKey) => hiddenKey !== key)
                      : [...layout.indicators.hidden, key],
                  })
                }
              />{" "}
              {t(`plan.indicators.${key}`)}
            </label>
          ))}
        </fieldset>
      )}
      {failed && <p role="alert">{t("plan.layout.failed")}</p>}
      <div className="layout-buttons">
        <button type="button" disabled={saving || layout.default === true} onClick={onReset}>
          {t("plan.layout.reset")}
        </button>
        <span className="spacer" />
        <button type="button" onClick={onClose}>
          {t("plan.layout.done")}
        </button>
      </div>
      <p className="dim" aria-live="polite">
        {saving ? t("plan.layout.saving") : ""}
      </p>
    </section>
  );
}
