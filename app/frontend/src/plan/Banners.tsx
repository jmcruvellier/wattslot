// Bandeaux d'une vue de jour (lot 5.3) : départ de la batterie (et dernière charge complète),
// météo (et fiabilité de la prévision au relevé), bilan des équipements — les bandeaux du
// dashboard de la v1, en données de l'API. Chacun est une tuile : un titre, un chiffre et sa
// pastille ; la phrase complète se déplie au toucher, pour ne pas allonger la page.

import { useI18n } from "../i18n/I18nProvider";
import type { Language } from "../i18n/translate";
import { clock, duration, kwh, percent, time } from "./format";
import type { ReactNode } from "react";

import type { DayView, Departure, DeviceStatus, ReadingWeather, Timeline, WeatherBanner } from "./types";
import Icon from "../ui/Icon";
import type { IconName } from "../ui/iconPaths";

// Météo du jour : soleil, nuages et soleil, nuages (lot 6b.7, à la place des emojis).
const WEATHER_ICONS = { sunny: "today", mixed: "cloud-sun", cloudy: "cloud" } as const;

function Badge({ tone, children }: { tone: "ok" | "medium" | "bad" | "neutral"; children: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function Tile({
  label,
  icon,
  title,
  value,
  badge,
  children,
}: {
  label: string; // nom de la tuile pour les lecteurs d'écran
  icon: IconName;
  title: string;
  value: string;
  badge?: ReactNode;
  children: ReactNode; // le détail, déplié au toucher
}) {
  return (
    <details className="plan-tile" aria-label={label}>
      <summary>
        <span className="plan-tile-title">
          <Icon name={icon} size={18} /> {title}
        </span>
        <strong className="plan-tile-value">{value}</strong>
        {badge}
        <Icon name="chevron-right" size={18} />
      </summary>
      <div className="plan-tile-detail">{children}</div>
    </details>
  );
}

function DepartureBanner({ departure }: { departure: Departure }) {
  const { language, t } = useI18n();
  const charge = departure.full_charge;
  const tone = { ok: "ok", reliable: "ok", medium: "medium", large: "bad", approximate: "bad" } as const;
  return (
    <Tile
      label={t("plan.banner.departure_title")}
      icon="battery"
      title={t("plan.banner.departure_title")}
      value={`${percent(departure.soc_percent)} %`}
      badge={departure.badge && <Badge tone={tone[departure.badge]}>{t(`plan.banner.departure_badge.${departure.badge}`)}</Badge>}
    >
      <span>
        {t(`plan.banner.departure.${departure.source}`, { kwh: kwh(departure.soc_kwh), pct: percent(departure.soc_percent) })}
        {departure.expected_kwh !== null &&
          ` — ${t("plan.banner.departure.expected", {
            time: departure.expected_at ? time(departure.expected_at, language) : "",
            kwh: kwh(departure.expected_kwh),
            pct: percent(departure.expected_percent),
          })}`}
        {departure.gap_points !== null && ` (${departure.gap_points > 0 ? "+" : ""}${departure.gap_points} pts)`}
        {charge && (
          <>
            <br />
            {charge.days === null
              ? t("plan.banner.charge.none", { days: charge.history_days ?? "" })
              : charge.days === 0
                ? t("plan.banner.charge.today")
                : charge.days === 1
                  ? t("plan.banner.charge.yesterday")
                  : t("plan.banner.charge.days", { days: charge.days })}
            {charge.priority && <strong> — {t("plan.banner.charge.priority")}</strong>}
          </>
        )}
      </span>
    </Tile>
  );
}

function WeatherPill({ weather, reading }: { weather: WeatherBanner; reading: ReadingWeather | null }) {
  const { language, t } = useI18n();
  const parts = [
    t(weather.measured ? "plan.banner.weather.measured" : "plan.banner.weather.forecast", { kwh: kwh(weather.production_kwh, 1) }),
  ];
  if (weather.quality && weather.share_percent !== null) {
    parts.push(t("plan.banner.weather.share", { pct: weather.share_percent, days: weather.best_days ?? "", kwh: kwh(weather.best_kwh, 1) }));
  }
  if (weather.today_gap_percent !== null) {
    parts.push(
      t("plan.banner.weather.vs_today", {
        gap: `${weather.today_gap_percent >= 0 ? "+" : ""}${weather.today_gap_percent}`,
        kwh: kwh(weather.today_estimate_kwh, 1),
      }),
    );
  }
  if (reading && reading.mode === "no_reading") parts.push(t("plan.banner.weather.no_reading"));
  if (reading && reading.mode !== "no_reading" && reading.measured_kwh !== null) {
    const gap = reading.gap_percent === null ? "" : `${reading.gap_percent >= 0 ? "+" : ""}${reading.gap_percent} % `;
    parts.push(
      reading.mode === "reading"
        ? t("plan.banner.weather.reading", { mes: kwh(reading.measured_kwh, 1), gap, est: kwh(reading.estimated_kwh, 1) })
        : t("plan.banner.weather.day", {
            gap,
            est: kwh(reading.estimated_kwh, 1),
            time: reading.initial_at ? time(reading.initial_at, language) : "",
          }),
    );
  }
  const tone = { reliable: "ok", moderate: "medium", important: "bad", too_early: "neutral" } as const;
  return (
    <Tile
      label={t("plan.banner.weather_title")}
      icon={weather.quality ? WEATHER_ICONS[weather.quality] : "today"}
      title={t(`plan.banner.weather.quality.${weather.quality ?? "unknown"}`)}
      value={`${kwh(weather.production_kwh, 1)} kWh`}
      badge={reading?.badge && <Badge tone={tone[reading.badge]}>{t(`plan.banner.weather.badge.${reading.badge}`)}</Badge>}
    >
      <span>{parts.join(" · ")}</span>
    </Tile>
  );
}

type Translate = ReturnType<typeof useI18n>["t"];

function statusText(status: DeviceStatus, t: Translate, lang: Language): string {
  const energy =
    status.actual_kwh === null
      ? ""
      : `${kwh(status.actual_kwh)} kWh${status.energy_gap_percent !== null ? ` (${status.energy_gap_percent > 0 ? "+" : "−"}${Math.abs(status.energy_gap_percent)} %)` : ""}${status.running ? `, ${t("plan.banner.equip.running")}` : ""}`;
  switch (status.status) {
    case "on_time":
      return t("plan.banner.equip.on_time", { device: status.device, time: clock(status.actual_start_min ?? 0, lang), kwh: energy });
    case "shifted":
      return t("plan.banner.equip.shifted", {
        device: status.device,
        shift: `${(status.shift_min ?? 0) > 0 ? "+" : "−"}${duration(status.shift_min ?? 0, lang)}`,
        actual: clock(status.actual_start_min ?? 0, lang),
        planned: clock(status.planned_start_min, lang),
        kwh: energy,
      });
    case "no_cycle":
      return t("plan.banner.equip.no_cycle", {
        device: status.device,
        start: clock(status.planned_start_min, lang),
        end: clock(status.planned_end_min, lang),
        kwh: kwh(status.planned_kwh),
      });
    default:
      return t("plan.banner.equip.planned", { device: status.device, start: clock(status.planned_start_min, lang) });
  }
}

function EquipmentPill({ timeline }: { timeline: Timeline }) {
  const { language, t } = useI18n();
  const lines = [
    ...timeline.statuses.map((status) => statusText(status, t, language)),
    ...timeline.unplanned.map((u) =>
      t("plan.banner.equip.unplanned", { device: u.device, time: clock(u.start_min, language), kwh: kwh(u.energy_kwh) }),
    ),
  ];
  // Lancés : vus dans les mesures, à l'heure, décalés ou hors plan.
  const started =
    timeline.statuses.filter((status) => status.status === "on_time" || status.status === "shifted").length +
    timeline.unplanned.length;
  return (
    <Tile
      label={t("plan.banner.equip_title")}
      icon="plug"
      title={t("plan.banner.equip_title")}
      value={t("plan.banner.equip.started", { started, total: lines.length })}
      badge={
        timeline.badge && (
          <Badge tone={timeline.badge === "on_time" ? "ok" : "medium"}>{t(`plan.banner.equip.badge.${timeline.badge}`)}</Badge>
        )
      }
    >
      <ul className="equip">
        {lines.length ? lines.map((line) => <li key={line}>{line}</li>) : <li>{t("plan.banner.equip.none")}</li>}
      </ul>
    </Tile>
  );
}

export default function Banners({ view }: { view: DayView }) {
  return (
    <div className="banners">
      {view.departure && <DepartureBanner departure={view.departure} />}
      {view.solar !== false && <WeatherPill weather={view.weather} reading={view.cards?.weather ?? null} />}
      {view.kind !== "tomorrow" && <EquipmentPill timeline={view.timeline} />}
    </div>
  );
}
