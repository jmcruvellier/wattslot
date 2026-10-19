// Vue Semaine (lot 5.4), comme `dashboard_semaine.py` de la v1 : aujourd'hui puis les 7 jours de
// l'horizon, une carte par jour (production et météo, SoC, achat dont heures pleines, surplus,
// équipements placés ce jour-là, avertissements), avertissements du calcul de l'horizon ;
// graphiques de la production, de la consommation de base et du SoC sur toute la semaine.
// Section Planning (lot 6b.4) : la semaine d'abord en agenda, une ligne par jour (`WeekAgenda`) ;
// les cartes des jours et les graphiques (`WeekDetails`) vont dans la section Courbes.

import { Suspense } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { clock, kwh, percent, time } from "./format";
import { availableWeekCards, shownCards, type ViewLayout, type WeekCardId } from "./layout";
import { WeekChart } from "./lazyCharts";
import type { DayKind, Notice, WeekDay, WeekView } from "./types";
import type { WeekSeries } from "./Charts";
import Icon from "../ui/Icon";
import type { IconName } from "../ui/iconPaths";

// Météo du jour : soleil, nuages et soleil, nuages (lot 6b.7, à la place des emojis).
const WEATHER_ICONS = { sunny: "today", mixed: "cloud-sun", cloudy: "cloud" } as const;

function Notices({ notices, label }: { notices: Notice[]; label: string }) {
  if (!notices.length) return null;
  return (
    <ul className="notices" aria-label={label}>
      {notices.map((notice, index) => (
        <li key={`${notice.code}-${index}`} className={notice.info ? "pill" : "pill pill-warning"}>
          <Icon name={notice.info ? "info" : "warning"} size={18} />{" "}
          {notice.text}
        </li>
      ))}
    </ul>
  );
}

function DayCard({ day, onOpen }: { day: WeekDay; onOpen: (kind: DayKind) => void }) {
  const { language, t } = useI18n();
  const title = new Date(`${day.day}T12:00:00`).toLocaleDateString(language, { weekday: "long", day: "numeric" });
  const withBattery = day.soc_start_percent !== null || day.soc_end_percent !== null;
  return (
    <article className={day.detail_view === "today" ? "card week-day week-today" : "card week-day"} aria-label={title}>
      <header>
        <h3>
          {title}
          {day.detail_view && <span className="week-tag">{t(`plan.tabs.${day.detail_view}`)}</span>}
        </h3>
        {day.weather && (
          <span className="dim">
            <Icon name={WEATHER_ICONS[day.weather]} size={18} /> {t(`plan.week.weather.${day.weather}`)}
          </span>
        )}
      </header>
      <dl className="week-figures">
        <dt>{t("plan.week.production")}</dt>
        <dd>{kwh(day.production_kwh, 1)} kWh</dd>
        {withBattery && (
          <>
            <dt>{t("plan.week.soc")}</dt>
            <dd>
              {t("plan.week.soc_value", { start: percent(day.soc_start_percent), end: percent(day.soc_end_percent) })}
            </dd>
            <dt className="sub">{t("plan.week.soc_max")}</dt>
            <dd className="sub">{percent(day.soc_max_percent)} %</dd>
          </>
        )}
        <dt>{t("plan.week.import")}</dt>
        <dd>{kwh(day.grid_import_kwh)} kWh</dd>
        <dt className="sub">{t("plan.week.import_peak")}</dt>
        <dd className="sub">{kwh(day.grid_import_peak_kwh)} kWh</dd>
        <dt>{t("plan.week.export")}</dt>
        <dd>{kwh(day.grid_export_kwh)} kWh</dd>
      </dl>
      <h4>{t("plan.week.devices")}</h4>
      <ul className="week-devices">
        {day.devices.length ? (
          day.devices.map((device) => (
            <li key={`${device.device}-${device.start_min}`}>
              <span>{device.device === "Batterie" ? t("plan.timeline.battery") : device.device}</span>
              <span className="dim">
                {clock(device.start_min, language)}–{clock(device.end_min, language)}
              </span>
            </li>
          ))
        ) : (
          <li className="dim">{t("plan.week.no_device")}</li>
        )}
      </ul>
      <Notices notices={day.notices} label={t("plan.notices")} />
      {day.detail_view && (
        <button type="button" className="link" onClick={() => onOpen(day.detail_view!)}>
          {t("plan.week.detail")} →
        </button>
      )}
    </article>
  );
}

/** Carte d'un jour que le calcul n'a pas atteint (section Courbes). */
function MissingDayCard({ day }: { day: string }) {
  const { language, t } = useI18n();
  const title = dayName(day, language);
  return (
    <article className="card week-day week-missing" aria-label={title}>
      <header>
        <h3>{title}</h3>
      </header>
      <p className="dim">
        <Icon name="warning" size={18} /> {t("plan.week.missing_curves")}
      </p>
    </article>
  );
}

const CHART_ICONS: Record<WeekSeries, IconName> = { production: "today", consumption: "home", soc: "battery" };

function WeekChartCard({ view, series }: { view: WeekView; series: WeekSeries }) {
  const { t } = useI18n();
  const title = t(`plan.week.charts.${series}`);
  return (
    <article className="card card-wide" aria-label={title}>
      <h3>
        <Icon name={CHART_ICONS[series]} size={20} /> {title}
      </h3>
      {series !== "production" && <p className="dim week-legend">▮ {t("plan.week.off_peak")}</p>}
      <Suspense fallback={<p>{t("plan.loading")}</p>}>
        <WeekChart points={view.points} series={series} nowIndex={view.now_index} floor={view.floor_percent} />
      </Suspense>
    </article>
  );
}

/** Nom d'un jour de la semaine : « lundi 19 ». */
function dayName(iso: string, language: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(language, { weekday: "long", day: "numeric" });
}

function WeekAgenda({ view, onOpen }: { view: WeekView; onOpen: (kind: DayKind) => void }) {
  const { language, t } = useI18n();
  return (
    <ol className="week-agenda" aria-label={t("plan.week.agenda")}>
      {view.days.map((day) => {
        const name = dayName(day.day, language);
        const devices = day.devices.filter((device) => device.device !== "Batterie");
        const withBattery = day.soc_max_percent !== null;
        return (
          <li key={day.day} className={day.detail_view === "today" ? "week-row week-row-today" : "week-row"}>
            <div className="week-row-head">
              <span className="week-row-day">
                {name}
                {day.detail_view && <span className="week-tag">{t(`plan.tabs.${day.detail_view}`)}</span>}
              </span>
              <span className="week-row-sun">
                {day.weather && <Icon name={WEATHER_ICONS[day.weather]} size={18} />}{" "}
                {day.weather ? `${t(`plan.week.weather.${day.weather}`)} · ` : ""}
                {kwh(day.production_kwh, 1)} kWh
              </span>
            </div>
            {withBattery && (
              <p className="week-row-battery">
                {t("plan.week.battery_line", {
                  start: percent(day.soc_start_percent),
                  max: percent(day.soc_max_percent),
                  end: percent(day.soc_end_percent),
                })}
              </p>
            )}
            <p className="week-row-devices">
              {devices.length
                ? devices.map((device) => `${device.device} ${clock(device.start_min, language)}`).join(" · ")
                : t("plan.week.no_device")}
            </p>
            {day.notices.length > 0 && (
              <p className="week-row-notice dim">{day.notices.map((notice) => notice.text).join(" ")}</p>
            )}
            {day.detail_view && (
              <button type="button" className="link" onClick={() => onOpen(day.detail_view!)}>
                {t("plan.week.open_day", { day: t(`plan.tabs.${day.detail_view}`) })} →
              </button>
            )}
          </li>
        );
      })}
      {/* Jours que le calcul n'a pas atteints : affichés quand même, sans données. */}
      {view.missing_days.map((day) => (
        <li key={day} className="week-row week-row-missing">
          <div className="week-row-head">
            <span className="week-row-day">{dayName(day, language)}</span>
          </div>
          <p className="dim">{t("plan.week.missing")}</p>
        </li>
      ))}
    </ol>
  );
}

/** Cartes des jours et graphiques de la semaine, dans l'ordre de la disposition (lot 5.5). */
export function WeekDetails({
  view,
  onOpen,
  layout,
}: {
  view: WeekView;
  onOpen: (kind: DayKind) => void;
  layout: ViewLayout;
}) {
  const { t } = useI18n();
  // Les graphiques se rangent en grilles avant ou après les cartes des jours, selon l'ordre choisi.
  const segments: WeekCardId[][] = [];
  for (const id of shownCards(layout, availableWeekCards(view))) {
    const last = segments[segments.length - 1];
    if (id !== "days" && last && last[0] !== "days") last.push(id);
    else segments.push([id]);
  }
  return (
    <div className="card-stack">
      {segments.map((segment) =>
        segment[0] === "days" ? (
          <section key="days" className="week-days" aria-label={t("plan.tabs.week")}>
            {view.days.map((day) => (
              <DayCard key={day.day} day={day} onOpen={onOpen} />
            ))}
            {view.missing_days.map((day) => (
              <MissingDayCard key={day} day={day} />
            ))}
          </section>
        ) : (
          <div key={segment[0]} className="cards cards-fill">
            {segment.map((series) => (
              <WeekChartCard key={series} view={view} series={series as WeekSeries} />
            ))}
          </div>
        ),
      )}
    </div>
  );
}

// « Calculer » est à droite des onglets (`PlanActions`).
export default function WeekScreen({ view, onOpen }: { view: WeekView; onOpen: (kind: DayKind) => void }) {
  const { language, t } = useI18n();
  const longDay = (iso: string) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString(language, { weekday: "long", day: "numeric", month: "long" });
  const first = view.days[0];
  const last = view.days[view.days.length - 1];

  return (
    <>
      <div className="view-header">
        <p>
          <strong>{first && last ? t("plan.week.title", { start: longDay(first.day), end: longDay(last.day) }) : t("plan.tabs.week")}</strong>
          <br />
          <small>
            {view.computed_at
              ? t("plan.week.computed", {
                  time: time(view.computed_at, language),
                  how: t(view.manual ? "plan.header.manual" : "plan.header.auto"),
                })
              : t("plan.header.never")}
            {view.seconds !== null && ` · ${t("plan.week.seconds", { seconds: kwh(view.seconds, 1) })}`}
          </small>
        </p>
      </div>
      <Notices notices={view.notices} label={t("plan.notices")} />
      {view.waiting_not_assigned && <p className="pill">ℹ️ {t("plan.week.waiting")}</p>}
      {view.days.length === 0 && <p className="pill">ℹ️ {t("plan.missing_week")}</p>}
      {view.days.length > 0 && <WeekAgenda view={view} onOpen={onOpen} />}
    </>
  );
}
