// Planning des équipements (lot 5.3) : une ligne par équipement, barres prévues (contour) et
// réelles (pleines) sur 24 heures, ligne du dernier relevé, info-bulle au toucher. Faite main
// (point n° 2 de la phase 5), positions en pourcentage de la journée comme la frise de la v1.
// Deux couloirs par piste (lot 7.1) : le prévu en haut, le réel en bas, chaque bloc portant son
// énergie, centrée sur sa plus grande partie visible, s'il lui reste assez de place libre ; pas de
// légende, le détail est dans l'info-bulle.

import { useCallback, useEffect, useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { hour, kwh } from "./format";
import { freeSpan } from "./timelineSpan";
import type { Bar, TimelineRow, Timeline } from "./types";
import Icon from "../ui/Icon";

const AXIS = [0, 4, 8, 12, 16, 20, 24];
// Place libre minimale, en pixels, pour écrire l'énergie d'un bloc (« 12,5 kWh » et ses marges).
const LABEL_MIN_PX = 50;

/** Largeur affichée de la piste (toutes les pistes ont la même), donnée par l'observateur dès le
 * début puis à chaque redimensionnement ; 0 sans ResizeObserver : aucun libellé dans les blocs. */
function useTrackWidth(): [number, (element: HTMLDivElement | null) => void] {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(element.getBoundingClientRect().width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [width, useCallback((node: HTMLDivElement | null) => setElement(node), [])];
}

function color(row: TimelineRow, bar: Bar): string {
  if (bar.action) return bar.action === "charge" ? "var(--charge)" : "var(--discharge)";
  if (row.kind === "runtime") return bar.mode === "eco" ? "var(--pool-eco)" : "var(--pool-silence)";
  return "var(--cycle)";
}

export default function TimelineCard({ timeline, readingHour }: { timeline: Timeline; readingHour: number | null }) {
  const { language, t } = useI18n();
  const [tip, setTip] = useState<string | null>(null);
  const [trackWidth, measureTrack] = useTrackWidth();
  const lang = language === "fr" ? "fr" : "en";

  const describe = (row: TimelineRow, bar: Bar, actual: boolean) => {
    const what = bar.action
      ? t(`plan.timeline.${bar.action}`)
      : bar.mode
        ? t("plan.timeline.mode", { mode: bar.mode })
        : row.device;
    return t(actual ? "plan.timeline.tip_actual" : "plan.timeline.tip_planned", {
      start: hour(Math.round(bar.start_hour * 60) / 60, lang),
      end: hour(Math.round(bar.end_hour * 60) / 60, lang),
      what,
      kwh: kwh(bar.energy_kwh),
    });
  };

  const bars = (row: TimelineRow, items: Bar[], actual: boolean) =>
    items.map((bar, index) => {
      const text = describe(row, bar, actual);
      const [free_start, free_end] = freeSpan(items, index);
      const wide = ((free_end - free_start) / 24) * trackWidth >= LABEL_MIN_PX;
      const duration = bar.end_hour - bar.start_hour;
      return (
        <button
          key={`${actual ? "a" : "p"}-${index}`}
          type="button"
          className={actual ? "tl-bar tl-actual" : "tl-bar tl-planned"}
          style={{
            left: `${(bar.start_hour / 24) * 100}%`,
            width: `max(3px, ${((bar.end_hour - bar.start_hour) / 24) * 100}%)`,
            ["--bar" as string]: color(row, bar),
          }}
          title={text}
          aria-label={text}
          onClick={() => setTip(text)}
        >
          {wide && (
            <span
              className="tl-value"
              aria-hidden="true"
              style={{ left: `${(((free_start + free_end) / 2 - bar.start_hour) / duration) * 100}%` }}
            >
              {kwh(bar.energy_kwh, 1)} kWh
            </span>
          )}
        </button>
      );
    });

  return (
    <article className="card card-wide" aria-label={t("plan.timeline.title")}>
      <h3>
        <Icon name="planning" size={20} /> {t("plan.timeline.title")}
      </h3>
      {timeline.empty ? (
        <p className="dim">
          {timeline.empty === "no_surplus"
            ? t("plan.timeline.no_surplus", {
                production: kwh(timeline.production_kwh, 1),
                consumption: kwh(timeline.consumption_kwh, 1),
              })
            : t("plan.timeline.nothing")}
        </p>
      ) : (
        <div className="tl">
          {timeline.rows.map((row, index) => (
            <div key={row.device} className="tl-row" aria-label={row.device}>
              <span className="tl-label">{row.device === "Batterie" ? t("plan.timeline.battery") : row.device}</span>
              <div className="tl-track" ref={index === 0 ? measureTrack : undefined}>
                {bars(row, row.planned, false)}
                {bars(row, row.actual, true)}
                {readingHour !== null && <span className="tl-now" style={{ left: `${(readingHour / 24) * 100}%` }} />}
              </div>
            </div>
          ))}
          <div className="tl-row" aria-hidden="true">
            <span />
            <div className="tl-axis">
              {AXIS.map((h) => (
                <span key={h} style={{ left: `${(h / 24) * 100}%` }}>
                  {hour(h, lang)}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
      {tip && <p role="status">{tip}</p>}
    </article>
  );
}
