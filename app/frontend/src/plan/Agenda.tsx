// Agenda d'un jour (lot 6b.4) : la journée en une phrase, puis les actions datées. Pour
// Aujourd'hui, les actions passées sont grisées et un repère « maintenant » les sépare des
// suivantes.

import type { ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { agenda, type AgendaEntry, firstUpcoming, sunWindow } from "./agendaEntries";
import { clock, duration, kwh, percent } from "./format";
import type { DayView } from "./types";
import Card from "../ui/Card";

function nowMinute(): number {
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

export function DaySummaryCard({ view }: { view: DayView }) {
  const { language, t } = useI18n();
  const weekday = new Date(`${view.day}T12:00:00`).toLocaleDateString(language, { weekday: "long" });
  const day = weekday.charAt(0).toUpperCase() + weekday.slice(1);
  const quality = view.weather.quality;
  const sun = sunWindow(view);
  const production = kwh(view.summary.production_kwh, 1);
  return (
    <Card
      tone="sun"
      title={quality ? t("plan.agenda.day_quality", { day, quality: t(`plan.agenda.quality.${quality}`) }) : day}
    >
      <p>
        {sun
          ? t("plan.agenda.sun_window", { kwh: production, start: sun[0], end: sun[1] })
          : t("plan.agenda.sun_none")}
      </p>
    </Card>
  );
}

function Entry({ entry, past }: { entry: AgendaEntry; past: boolean }) {
  const { language, t } = useI18n();
  let title: string;
  let detail: string | null = null;
  switch (entry.kind) {
    case "cycle":
      title = t("plan.agenda.cycle", { device: entry.device });
      detail = entry.explanation;
      break;
    case "runtime":
      title = t("plan.agenda.runtime", { device: entry.device, duration: duration(entry.end - entry.minute, language) });
      detail = entry.mode ? t("plan.agenda.mode", { mode: entry.mode }) : null;
      break;
    case "battery_charge":
      title = t("plan.agenda.battery_charge");
      detail = t("plan.agenda.until", { time: clock(entry.end, language) });
      break;
    case "battery_discharge":
      title = t("plan.agenda.battery_discharge");
      detail = t("plan.agenda.until", { time: clock(entry.end, language) });
      break;
    case "battery_max":
      title = t("plan.agenda.battery_max", { pct: percent(entry.percent) });
      break;
  }
  return (
    <li className={past ? "agenda-entry agenda-past" : "agenda-entry"} data-kind={entry.kind}>
      <span className="agenda-time">{clock(entry.minute, language)}</span>
      <span>
        <span className="agenda-title">{title}</span>
        {detail && <span className="agenda-detail">{detail}</span>}
      </span>
    </li>
  );
}

export default function Agenda({ view }: { view: DayView }) {
  const { t } = useI18n();
  const entries = agenda(view);
  if (entries.length === 0) {
    return (
      <Card>
        <p>{t("plan.agenda.empty")}</p>
      </Card>
    );
  }
  const upcoming = view.kind === "today" ? firstUpcoming(entries, nowMinute()) : -1;
  return (
    <ol className="agenda" aria-label={t("plan.agenda.title")}>
      {entries.map((entry, index) => (
        <Fragmented key={`${entry.kind}-${entry.minute}-${index}`} marker={index === upcoming && upcoming > 0}>
          <Entry entry={entry} past={view.kind === "yesterday" ? false : index < upcoming} />
        </Fragmented>
      ))}
    </ol>
  );
}

// Repère « maintenant » avant la première action à venir.
function Fragmented({ marker, children }: { marker: boolean; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <>
      {marker && (
        <li className="agenda-now" aria-label={t("plan.agenda.now")}>
          <span>{t("plan.agenda.now")}</span>
        </li>
      )}
      {children}
    </>
  );
}
