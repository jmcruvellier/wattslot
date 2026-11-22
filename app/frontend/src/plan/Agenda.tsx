// Agenda d'un jour (lot 6b.4) : « La journée », une ligne par événement — l'heure, ce qui se
// passe, et à droite sa fin (batterie) ou son énergie (appareil : « lancé · 3,8 kWh » une fois
// vu dans les mesures). Pour Aujourd'hui, un repère « Maintenant » sépare le passé de la suite.
// La raison d'un créneau se déplie au toucher, avec ses autres départs (Aujourd'hui) ; ce que
// « Pourquoi ce plan » dit d'autre (la batterie, le texte entier du plan) se déplie en bas.

import type { ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { minuteOfDay } from "../i18n/homeTime";
import { agenda, type AgendaEntry, firstUpcoming, otherExplanations } from "./agendaEntries";
import { batteryLabel } from "./batteryLabel";
import { clock, duration, hour, kwh, percent } from "./format";
import OtherStarts from "./OtherStarts";
import type { DayView } from "./types";
import Icon from "../ui/Icon";

function nowMinute(): number {
  return minuteOfDay(); // heure de la maison, celle des heures du plan
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
  onChanged,
}: {
  entry: AgendaEntry;
  onChanged?: () => void; // Aujourd'hui : les autres départs se choisissent ici
}) {
  const { language, t } = useI18n();
  const time = <span className="agenda-time">{hour(entry.minute / 60, language)}</span>;

  if (entry.kind === "cycle") {
    // Vu dans les mesures : l'énergie mesurée, en pastille ; sinon l'énergie prévue.
    const energy = entry.launched ? (
      <span className="badge badge-ok">
        {t("plan.agenda.launched")} · {kwh(entry.actual_kwh ?? entry.energy_kwh)} kWh
      </span>
    ) : (
      <span className="agenda-detail">{kwh(entry.energy_kwh)} kWh</span>
    );
    if (!entry.explanation && !entry.chosen) {
      return (
        <li className="agenda-entry agenda-row" data-kind="cycle">
          {time}
          <span className="agenda-title">{entry.device}</span>
          {energy}
        </li>
      );
    }
    const now = nowMinute();
    return (
      <li className="agenda-entry" data-kind="cycle">
        <details>
          <summary className="agenda-row">
            {time}
            <span className="agenda-title">
              {entry.device} <Icon name="chevron-right" size={16} />
            </span>
            {energy}
          </summary>
          <div className="agenda-why">
            {entry.explanation && <p>{entry.explanation}</p>}
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

  let title: string;
  let detail: string | null = null;
  switch (entry.kind) {
    case "runtime":
      title = t("plan.agenda.runtime", { device: entry.device, duration: duration(entry.end - entry.minute, language) });
      detail = entry.mode ? t("plan.agenda.mode", { mode: entry.mode }) : null;
      break;
    case "battery_charge":
      title = batteryTitle(entry.phase, "charge", t);
      detail = t("plan.agenda.until", { time: hour(entry.end / 60, language) });
      break;
    case "battery_discharge":
      title = batteryTitle(entry.phase, "discharge", t);
      detail = t("plan.agenda.until", { time: hour(entry.end / 60, language) });
      break;
    case "battery_max":
      title = t("plan.agenda.battery_max", { pct: percent(entry.percent) });
      break;
  }
  return (
    <li className="agenda-entry agenda-row" data-kind={entry.kind}>
      {time}
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
  why?: boolean; // « Pourquoi ce plan » déplié en bas de la carte (Planning)
}) {
  const { language, t } = useI18n();
  const entries = agenda(view);
  const others = why ? otherExplanations(view, entries) : [];
  const more = why && (others.length > 0 || view.recommendation !== null) && (
    <details className="plan-why">
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
  const upcoming = view.kind === "today" ? firstUpcoming(entries, nowMinute()) : -1;
  return (
    <section className="ui-card ui-panel agenda-card" aria-labelledby="agenda-heading">
      <div className="ui-panel-head">
        <h3 id="agenda-heading" className="ui-panel-title">
          {t("plan.agenda.heading")}
        </h3>
      </div>
      {entries.length === 0 ? (
        <p>{t("plan.agenda.empty")}</p>
      ) : (
        <ol className="agenda" aria-label={t("plan.agenda.title")}>
          {entries.map((entry, index) => (
            <Fragmented
              key={`${entry.kind}-${entry.minute}-${index}`}
              marker={index === upcoming && upcoming > 0 ? clock(nowMinute(), language) : null}
            >
              <Entry entry={entry} onChanged={view.kind === "today" ? onChanged : undefined} />
            </Fragmented>
          ))}
        </ol>
      )}
      {more}
    </section>
  );
}

// Repère « Maintenant · 14h30 » avant la première action à venir.
function Fragmented({ marker, children }: { marker: string | null; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <>
      {marker !== null && (
        <li className="agenda-now" aria-label={t("plan.agenda.now")}>
          {t("plan.agenda.now")} · {marker}
        </li>
      )}
      {children}
    </>
  );
}
