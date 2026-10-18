// En-tête d'une vue de jour (lot 5.3) : date, calcul (heure, automatique ou à la main), dernier
// relevé ; « Calculer » (Aujourd'hui, Demain) et « Rafraîchir les données réelles »
// (Aujourd'hui), comme dans la v1 ; calculs interrompus, avertissements et tâches reportées.

import { useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { longDate, time } from "./format";
import type { DayView } from "./types";
import Icon from "../ui/Icon";

type Action = "idle" | "running" | "failed";

export default function ViewHeader({ view, onChanged }: { view: DayView; onChanged: () => void }) {
  const { language, t } = useI18n();
  const [action, setAction] = useState<Action>("idle");

  const run = async (url: string) => {
    setAction("running");
    try {
      const response = await fetch(url, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setAction("idle");
      onChanged();
    } catch {
      setAction("failed");
    }
  };

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
        <span className="spacer" />
        {view.kind !== "yesterday" && (
          <button type="button" disabled={action === "running"} onClick={() => void run("api/planning/run")}>
            {t(action === "running" ? "plan.header.running" : "plan.header.compute")}
          </button>
        )}
        {view.kind === "today" && (
          <button type="button" disabled={action === "running"} onClick={() => void run("api/planning/actual")}>
            {t("plan.header.refresh")}
          </button>
        )}
      </div>
      {action === "failed" && <p role="alert">{t("plan.header.failed")}</p>}
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
