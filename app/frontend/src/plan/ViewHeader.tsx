// En-tête d'une vue de jour (lot 5.3) : date, calcul (heure, automatique ou à la main), dernier
// relevé ; calculs interrompus, avertissements et tâches reportées. « Calculer » et « Rafraîchir
// les données réelles » sont dans la barre de titre de la section (`PlanActions`).

import { useI18n } from "../i18n/I18nProvider";
import { longDate, time } from "./format";
import type { DayView } from "./types";
import Icon from "../ui/Icon";

export default function ViewHeader({ view }: { view: DayView }) {
  const { language, t } = useI18n();

  return (
    <>
      <div className="view-header">
        <p>
          <strong>{longDate(view.day, language)}</strong>
          <br />
          <small>
            {view.computed_at
              ? t("plan.header.computed", {
                  time: time(view.computed_at, language),
                  how: t(view.manual ? "plan.header.manual" : "plan.header.auto"),
                })
              : t("plan.header.never")}
            {view.actual_updated_at &&
              ` · ${t("plan.header.reading", { time: time(view.actual_updated_at, language) })}`}
          </small>
        </p>
      </div>
      {view.freshness && (
        <p className="pill pill-warning">
          {view.freshness.code === "stale_today"
            ? t("plan.freshness.stale_today", {
                hours: Math.floor((view.freshness.minutes ?? 0) / 60),
                minutes: String((view.freshness.minutes ?? 0) % 60).padStart(2, "0"),
              })
            : t("plan.freshness.stopped_yesterday", {
                time: view.freshness.last_at ? time(view.freshness.last_at, language) : "",
              })}
        </p>
      )}
      {view.notices.length > 0 && (
        <ul className="notices" aria-label={t("plan.notices")}>
          {view.notices.map((notice, index) => (
            <li key={`${notice.code}-${index}`} className={notice.info ? "pill" : "pill pill-warning"}>
              <Icon name={notice.info ? "info" : "warning"} size={18} />{" "}
              {notice.text}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
