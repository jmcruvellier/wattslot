// Bandeaux d'une vue de jour (lot 5.3) : départ de la batterie (et dernière charge complète),
// météo (et fiabilité de la prévision au relevé), bilan des équipements — les bandeaux du
// dashboard de la v1, en données de l'API. Chacun est une tuile : un titre, un chiffre et sa
// pastille, puis le détail en lignes « libellé, valeur » (une ligne par appareil pour les
// équipements) : déplié d'emblée sur un écran large, où la place ne manque pas, replié sur
// téléphone pour ne pas allonger la page ; le chevron le replie ou le déplie.

import { useI18n } from "../i18n/I18nProvider";
import type { Language } from "../i18n/translate";
import { sunWindow } from "./agendaEntries";
import { clock, duration, hour, kwh, percent, time } from "./format";
import { useState, type ReactNode } from "react";

import type { DayView, Departure, DeviceStatus, ReadingWeather, Timeline, WeatherBanner } from "./types";
import Icon from "../ui/Icon";
import { wideScreen } from "./wideScreen";

function Badge({ tone, children }: { tone: "ok" | "medium" | "bad" | "neutral"; children: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function Tile({
  label,
  title,
  value,
  badge,
  children,
}: {
  label: string; // nom de la tuile pour les lecteurs d'écran
  title: string;
  value: string;
  badge?: ReactNode;
  children: ReactNode; // le détail, sous le chiffre
}) {
  const [open, setOpen] = useState(wideScreen);
  return (
    <details
      className="plan-tile"
      aria-label={label}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span className="plan-tile-title">{title}</span>
        <strong className="plan-tile-value">{value}</strong>
        {badge}
        <Icon name="chevron-right" size={16} />
      </summary>
      <div className="plan-tile-detail">{children}</div>
    </details>
  );
}

/** Détail d'une tuile : une ligne par information, le libellé à gauche, la valeur à droite. */
function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="plan-tile-rows">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** « +5 % », « −3 % » : le signe toujours écrit. */
function signed(value: number, unit: string): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value)} ${unit}`;
}

function DepartureBanner({ departure }: { departure: Departure }) {
  const { language, t } = useI18n();
  const charge = departure.full_charge;
  const tone = { ok: "ok", reliable: "ok", medium: "medium", large: "bad", approximate: "bad" } as const;
  const level = (energy: number | null, share: number | null) => `${kwh(energy)} kWh · ${percent(share)} %`;
  const rows: [string, ReactNode][] = [
    [t(`plan.banner.rows.src_${departure.source}`), level(departure.soc_kwh, departure.soc_percent)],
  ];
  if (departure.expected_kwh !== null) {
    rows.push([
      t("plan.banner.rows.expected", { time: departure.expected_at ? time(departure.expected_at, language) : "" }),
      level(departure.expected_kwh, departure.expected_percent),
    ]);
  }
  if (departure.gap_points !== null) rows.push([t("plan.banner.rows.gap"), signed(departure.gap_points, "pts")]);
  if (charge) {
    // « aujourd'hui », « hier », « il y a 3 jours » : dans la langue, sans texte à traduire.
    const ago = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
    rows.push([
      t("plan.banner.rows.full_charge"),
      charge.days === null
        ? t("plan.banner.rows.none_since", { days: charge.history_days ?? "" })
        : ago.format(-charge.days, "day"),
    ]);
  }
  return (
    <Tile
      label={t("plan.banner.departure_title")}
      title={t("plan.banner.departure_tile")}
      value={`${percent(departure.soc_percent)} %`}
      badge={departure.badge && <Badge tone={tone[departure.badge]}>{t(`plan.banner.departure_badge.${departure.badge}`)}</Badge>}
    >
      <Rows rows={rows} />
      {charge?.priority && <p className="plan-tile-note">{t("plan.banner.charge.priority")}</p>}
    </Tile>
  );
}

function WeatherPill({
  weather,
  reading,
  sun,
}: {
  weather: WeatherBanner;
  reading: ReadingWeather | null;
  sun: [number, number] | null; // heures où le soleil produit le plus
}) {
  const { language, t } = useI18n();
  const energy = (value: number | null) => `${kwh(value, 1)} kWh`;
  const rows: [string, ReactNode][] = [
    [t("plan.banner.weather_title"), t(`plan.banner.weather.quality.${weather.quality ?? "unknown"}`)],
  ];
  if (weather.quality && weather.share_percent !== null) {
    rows.push([
      t("plan.banner.rows.best_day", { days: weather.best_days ?? "" }),
      `${energy(weather.best_kwh)} · ${weather.share_percent} %`,
    ]);
  }
  if (weather.today_gap_percent !== null) {
    rows.push([
      t("plan.banner.rows.vs_today"),
      `${signed(weather.today_gap_percent, "%")} · ${energy(weather.today_estimate_kwh)}`,
    ]);
  }
  if (reading && reading.mode === "no_reading") {
    rows.push([t("plan.banner.rows.reading"), t("plan.banner.weather.no_reading")]);
  }
  if (reading && reading.mode !== "no_reading" && reading.measured_kwh !== null) {
    const gap = reading.gap_percent === null ? "" : ` · ${signed(reading.gap_percent, "%")}`;
    if (reading.mode === "reading") {
      rows.push([t("plan.banner.rows.at_reading"), energy(reading.measured_kwh)]);
      rows.push([t("plan.banner.rows.last_forecast"), `${energy(reading.estimated_kwh)}${gap}`]);
    } else {
      rows.push([
        t("plan.banner.rows.forecast_at", { time: reading.initial_at ? time(reading.initial_at, language) : "" }),
        `${energy(reading.estimated_kwh)}${gap}`,
      ]);
    }
  }
  if (sun) rows.push([t("plan.banner.rows.full_sun"), `${hour(sun[0], language)} – ${hour(sun[1], language)}`]);
  const tone = { reliable: "ok", moderate: "medium", important: "bad", too_early: "neutral" } as const;
  // Écart du mesuré à la prévision, à côté de la pastille (« fiable · +5 % »).
  const gapPercent = reading && reading.mode !== "no_reading" ? reading.gap_percent : null;
  const trend = gapPercent == null ? null : `${gapPercent >= 0 ? "+" : ""}${gapPercent} %`;
  return (
    <Tile
      label={t("plan.banner.weather_title")}
      title={t(weather.measured ? "plan.banner.weather_tile_measured" : "plan.banner.weather_tile_forecast")}
      value={energy(weather.production_kwh)}
      badge={
        reading?.badge && (
          <Badge tone={tone[reading.badge]}>
            {`${t(`plan.banner.weather.badge.${reading.badge}`)}${trend ? ` · ${trend}` : ""}`}
          </Badge>
        )
      }
    >
      <Rows rows={rows} />
    </Tile>
  );
}

type Translate = ReturnType<typeof useI18n>["t"];

/** Un appareil de la tuile : son nom, où il en est, son énergie (mesurée, sinon prévue). */
function deviceLine(status: DeviceStatus, t: Translate, lang: Language): [string, string, string] {
  const gap = status.energy_gap_percent !== null ? ` (${signed(status.energy_gap_percent, "%")})` : "";
  const measured = status.actual_kwh === null ? "" : `${kwh(status.actual_kwh)} kWh${gap}`;
  const running = status.running ? `, ${t("plan.banner.equip.running")}` : "";
  switch (status.status) {
    case "on_time":
      return [status.device, t("plan.banner.rows.started", { time: clock(status.actual_start_min ?? 0, lang) }) + running, measured];
    case "shifted":
      return [
        status.device,
        t("plan.banner.rows.started_shifted", {
          time: clock(status.actual_start_min ?? 0, lang),
          shift: `${(status.shift_min ?? 0) > 0 ? "+" : "−"}${duration(status.shift_min ?? 0, lang)}`,
        }) + running,
        measured,
      ];
    case "no_cycle":
      return [
        status.device,
        t("plan.banner.rows.not_started", {
          start: clock(status.planned_start_min, lang),
          end: clock(status.planned_end_min, lang),
        }),
        `${kwh(status.planned_kwh)} kWh`,
      ];
    default:
      return [
        status.device,
        t("plan.banner.rows.planned", { time: clock(status.planned_start_min, lang) }),
        `${kwh(status.planned_kwh)} kWh`,
      ];
  }
}

function EquipmentPill({ timeline }: { timeline: Timeline }) {
  const { language, t } = useI18n();
  const judged: [string, string, string][] = [
    ...timeline.statuses.map((status) => deviceLine(status, t, language)),
    ...timeline.unplanned.map((u): [string, string, string] => [
      u.device,
      t("plan.banner.rows.unplanned", { time: clock(u.start_min, language) }),
      `${kwh(u.energy_kwh)} kWh`,
    ]),
  ];
  // Jour à venir : pas de bilan au relevé, mais les créneaux prévus de la frise (la fin d'un
  // cycle commencé la veille n'en est pas un).
  const lines =
    judged.length > 0
      ? judged
      : timeline.rows
          .filter((row) => row.kind === "cycle")
          .flatMap((row) =>
            row.planned
              .filter((bar) => !bar.carried)
              .map((bar): [string, string, string] => [
                bar.cycle ?? row.device,
                t("plan.banner.rows.planned", { time: clock(bar.start_hour * 60, language) }),
                `${kwh(bar.energy_kwh)} kWh`,
              ]),
          );
  // Lancés : vus dans les mesures, à l'heure, décalés ou hors plan.
  const started =
    timeline.statuses.filter((status) => status.status === "on_time" || status.status === "shifted").length +
    timeline.unplanned.length;
  const planned = lines.length - started;
  // « 3 lancés », « 2 prévus » ou « 2 lancés, 2 prévus » : jamais « 0 prévus » pour un jour passé.
  const count = (kind: "started" | "planned", n: number) => t(`plan.banner.equip.${kind}_${n === 1 ? "one" : "other"}`, { n });
  const counts = [started > 0 ? count("started", started) : null, planned > 0 ? count("planned", planned) : null];
  return (
    <Tile
      label={t("plan.banner.equip_title")}
      title={t("plan.banner.equip_tile")}
      value={
        lines.length === 0
          ? t("plan.banner.equip.nothing")
          : counts.filter(Boolean).join(", ")
      }
      badge={
        timeline.badge && (
          <Badge tone={timeline.badge === "on_time" ? "ok" : "medium"}>{t(`plan.banner.equip.badge.${timeline.badge}`)}</Badge>
        )
      }
    >
      {lines.length === 0 ? (
        <p className="plan-tile-note">{t("plan.banner.equip.none")}</p>
      ) : (
        <ul className="plan-tile-devices">
          {lines.map(([device, state, energy], index) => (
            <li key={`${device}-${index}`}>
              <span>{device}</span>
              <span className="plan-tile-state">{state}</span>
              <span>{energy}</span>
            </li>
          ))}
        </ul>
      )}
    </Tile>
  );
}

export default function Banners({ view }: { view: DayView }) {
  return (
    <div className="banners">
      {view.departure && <DepartureBanner departure={view.departure} />}
      {view.solar !== false && (
        <WeatherPill weather={view.weather} reading={view.cards?.weather ?? null} sun={sunWindow(view)} />
      )}
      <EquipmentPill timeline={view.timeline} />
    </div>
  );
}
