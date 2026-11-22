// Agenda d'un jour (lot 6b.4) : les heures où le soleil produit le plus, en une ligne (la date
// est dans l'en-tête de la vue, la météo et la production du jour dans les tuiles), puis les
// actions datées, une ligne chacune. Pour Aujourd'hui, les actions passées sont grisées et un repère « maintenant » les
// sépare des suivantes. La raison d'un créneau se déplie au toucher, avec ses autres départs
// (Aujourd'hui) ; ce que « Pourquoi ce plan » disait d'autre (la batterie, le texte entier de
// la recommandation) se déplie sous la liste.

import type { ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { minuteOfDay } from "../i18n/homeTime";
import { agenda, type AgendaEntry, firstUpcoming, otherExplanations, sunWindow } from "./agendaEntries";
import { batteryLabel } from "./batteryLabel";
import { clock, duration, percent } from "./format";
import OtherStarts from "./OtherStarts";
import type { DayView } from "./types";
import Card from "../ui/Card";
import Icon from "../ui/Icon";

function nowMinute(): number {
  return minuteOfDay(); // heure de la maison, celle des heures du plan
}

/** Les heures où le soleil produit le plus, en tête de l'agenda. */
export function SunHours({ view }: { view: DayView }) {
  const { t } = useI18n();
  const sun = sunWindow(view);
  if (view.solar === false) return null; // sans panneaux, la journée n'a pas de soleil à raconter
  return (
    <p className="agenda-sun">
      <Icon name="today" size={18} />
      {sun ? t("plan.agenda.sun_hours", { start: sun[0], end: sun[1] }) : t("plan.agenda.sun_none")}
    </p>
  );
}

// Phase de la batterie : celle de la maison, ou celle des batteries d'une phase nommée.
function batteryTitle(
  phase: number | null | undefined,
  action: "charge" | "discharge",
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  if (phase == null) return t(`plan.agenda.battery_${action}`);
  return t(`plan.agenda.battery_${action}_of`, { battery: batteryLabel(phase, t) });
}

function Entry({
  entry,
  past,
  onChanged,
}: {
  entry: AgendaEntry;
  past: boolean;
  onChanged?: () => void; // Aujourd'hui : les autres départs se choisissent ici
}) {
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
      title = batteryTitle(entry.phase, "charge", t);
      detail = t("plan.agenda.until", { time: clock(entry.end, language) });
      break;
    case "battery_discharge":
      title = batteryTitle(entry.phase, "discharge", t);
      detail = t("plan.agenda.until", { time: clock(entry.end, language) });
      break;
    case "battery_max":
      title = t("plan.agenda.battery_max", { pct: percent(entry.percent) });
      break;
  }
  const className = past ? "agenda-entry agenda-past" : "agenda-entry";
  // Un appareil : sa raison, et ses autres départs encore à venir, se déplient sous sa ligne.
  if (entry.kind === "cycle" && (detail || entry.chosen)) {
    const now = nowMinute();
    return (
      <li className={className} data-kind={entry.kind}>
        <details>
          <summary className="agenda-row">
            <span className="agenda-time">{clock(entry.minute, language)}</span>
            <span className="agenda-title">{title}</span>
            <Icon name="chevron-right" size={18} />
          </summary>
          <div className="agenda-why">
            {detail && <p>{detail}</p>}
            {onChanged && (
              <OtherStarts
                device={entry.device}
                alternatives={entry.alternatives.filter((other) => other.start_min > now)}
                chosen={entry.chosen}
                onChanged={onChanged}
              />
            )}
          </div>
        </details>
      </li>
    );
  }
  return (
    <li className={`${className} agenda-row`} data-kind={entry.kind}>
      <span className="agenda-time">{clock(entry.minute, language)}</span>
      <span className="agenda-title">{title}</span>
      {detail && <span className="agenda-detail">{detail}</span>}
    </li>
  );
}

export default function Agenda({
  view,
  onChanged,
  why = false,
}: {
  view: DayView;
  onChanged?: () => void; // Aujourd'hui : relit la vue après le choix d'un autre départ
  why?: boolean; // « Pourquoi ce plan » déplié sous la liste (Planning)
}) {
  const { t } = useI18n();
  const entries = agenda(view);
  const others = why ? otherExplanations(view, entries) : [];
  const more = why && (others.length > 0 || view.recommendation !== null) && (
    <details className="ui-card plan-why">
      <summary>{t("plan.explanations.title")}</summary>
      {others.length > 0 && (
        <ul className="explanations">
          {others.map((item, index) => (
            <li key={`${item.device}-${index}`}>
              <strong>{item.device}</strong> {item.text}
            </li>
          ))}
        </ul>
      )}
      {view.recommendation && <p className="recommendation">{view.recommendation}</p>}
    </details>
  );
  if (entries.length === 0) {
    return (
      <>
        <Card>
          <p>{t("plan.agenda.empty")}</p>
        </Card>
        {more}
      </>
    );
  }
  const upcoming = view.kind === "today" ? firstUpcoming(entries, nowMinute()) : -1;
  return (
    <>
      <ol className="agenda" aria-label={t("plan.agenda.title")}>
        {entries.map((entry, index) => (
          <Fragmented key={`${entry.kind}-${entry.minute}-${index}`} marker={index === upcoming && upcoming > 0}>
            <Entry
              entry={entry}
              past={view.kind === "yesterday" ? false : index < upcoming}
              onChanged={view.kind === "today" ? onChanged : undefined}
            />
          </Fragmented>
        ))}
      </ol>
      {more}
    </>
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
