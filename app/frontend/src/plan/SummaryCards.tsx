// Cartes de résumé d'une vue de jour (lot 5.3) : SoC, SoC max, batterie, réseau, production.
// Aujourd'hui et Hier : estimé et mesuré au relevé avec leur tendance, et pour Aujourd'hui la
// ligne « Journée » (premier calcul contre fin de journée recalculée). Demain : une valeur
// prévue par carte. Sans batterie, ni SoC ni carte Batterie. Sur grand écran, grille de six
// colonnes : les trois cartes de la batterie en occupent deux chacune, Réseau et Production trois.

import { useI18n } from "../i18n/I18nProvider";
import { hour, kwh, percent } from "./format";
import type { CardLine, DayView, LineKey, Trend } from "./types";
import Icon from "../ui/Icon";
import type { IconName } from "../ui/iconPaths";

// Cartes et leurs lignes, dans l'ordre de la v1.
const CARDS: { key: string; icon: IconName; lines: LineKey[]; battery: boolean }[] = [
  { key: "soc", icon: "battery", lines: ["soc"], battery: true },
  { key: "soc_max", icon: "arrow-up", lines: ["soc_max"], battery: true },
  { key: "battery", icon: "refresh", lines: ["charge", "discharge"], battery: true },
  { key: "grid", icon: "plug", lines: ["grid_import", "grid_export"], battery: false },
  { key: "production", icon: "today", lines: ["production"], battery: false },
];

const cardClass = (battery: boolean) => (battery ? "card" : "card summary-half");

function TrendMark({ trend }: { trend: Trend }) {
  const tone = trend.favorable === null ? "trend-neutral" : trend.favorable ? "trend-good" : "trend-bad";
  const text = {
    none: "—",
    stable: "● 0%",
    infinite: "▲", // estimé nul : pas de pourcentage
    up: `▲ +${trend.percent ?? 0}%`,
    down: `▼ ${trend.percent ?? 0}%`,
  }[trend.direction];
  return <span className={`trend ${tone}`}>{text}</span>;
}

function detail(line: CardLine, column: "estimated" | "measured", capacity: number | null, language: "fr" | "en"): string {
  const value = column === "estimated" ? line.estimated_kwh : line.measured_kwh;
  if (value === null) return "";
  if (line.key === "soc") {
    const pct = column === "measured" && line.measured_percent !== null ? line.measured_percent : capacity ? (value / capacity) * 100 : null;
    return pct === null ? "" : `${percent(pct)} %`;
  }
  if (line.key === "soc_max") {
    const pct = column === "measured" && line.measured_percent !== null ? line.measured_percent : capacity ? (value / capacity) * 100 : null;
    const at = column === "estimated" ? line.estimated_hour : line.measured_hour;
    return [pct === null ? null : `${percent(pct)} %`, at === null ? null : hour(at, language)].filter(Boolean).join(" · ");
  }
  return "";
}

function Rows({ lines, capacity, labels }: { lines: CardLine[]; capacity: number | null; labels: boolean }) {
  const { language, t } = useI18n();
  const lang = language === "fr" ? "fr" : "en";
  return (
    <>
      {lines.map((line) => (
        <div key={line.key} className="stat-row" aria-label={t(`plan.summary.lines.${line.key}`)}>
          <span className="stat-label">{labels ? t(`plan.summary.lines.${line.key}`) : ""}</span>
          <span className="stat-value dim">
            {kwh(line.estimated_kwh)}
            <small> kWh</small>
            <small className="stat-detail">{detail(line, "estimated", capacity, lang)}</small>
          </span>
          <span className="stat-value">
            {kwh(line.measured_kwh)}
            {line.measured_kwh !== null && <small> kWh</small>}
            <small className="stat-detail">{detail(line, "measured", capacity, lang)}</small>
          </span>
          <TrendMark trend={line.trend} />
        </div>
      ))}
    </>
  );
}

export default function SummaryCards({ view }: { view: DayView }) {
  const { language, t } = useI18n();
  const hasBattery = view.battery_capacity_kwh !== null;
  // Maison sans installation solaire (lot 7.4) : pas de carte de production.
  const shown = CARDS.filter((card) => (hasBattery || !card.battery) && (view.solar !== false || card.key !== "production"));

  if (view.kind === "tomorrow" || !view.cards) {
    const s = view.summary;
    const values: Record<LineKey, [number, string]> = {
      soc: [s.soc_end_kwh, `${percent(s.soc_end_percent)} % · 24h`],
      soc_max: [s.soc_max_kwh, `${percent(s.soc_max_percent)} % · ${hour(s.soc_max_hour, language === "fr" ? "fr" : "en")}`],
      charge: [s.charge_kwh, ""],
      discharge: [s.discharge_kwh, ""],
      grid_import: [s.grid_import_kwh, ""],
      grid_export: [s.grid_export_kwh, ""],
      production: [s.production_kwh, ""],
    };
    return (
      <div className="cards summary-cards">
        {shown.map((card) => (
          <article key={card.key} className={cardClass(card.battery)} aria-label={t(`plan.summary.cards.${card.key}`)}>
            <h3>
              <Icon name={card.icon} size={18} /> {t(`plan.summary.cards.${card.key}`)}
            </h3>
            <small className="dim">{t("plan.summary.forecast")}</small>
            {card.lines.map((key) => (
              <p key={key} className="stat-big" aria-label={t(`plan.summary.lines.${key}`)}>
                {card.lines.length > 1 && <span className="stat-label">{t(`plan.summary.lines.${key}`)} </span>}
                {kwh(values[key][0])}
                <small> kWh</small> <small className="dim">{values[key][1]}</small>
              </p>
            ))}
          </article>
        ))}
      </div>
    );
  }

  const byKey = (lines: CardLine[] | null) => new Map((lines ?? []).map((line) => [line.key, line]));
  const atReading = byKey(view.cards.at_reading);
  const day = byKey(view.cards.day);
  return (
    <div className="cards summary-cards">
      {shown.map((card) => (
        <article key={card.key} className={cardClass(card.battery)} aria-label={t(`plan.summary.cards.${card.key}`)}>
          <h3>
            <Icon name={card.icon} size={18} /> {t(`plan.summary.cards.${card.key}`)}
          </h3>
          <div className="stat-grid">
            <span />
            <small className="dim">{t("plan.summary.estimated")}</small>
            <small className="dim">{t("plan.summary.measured")}</small>
            <span />
            {view.kind === "today" && <small className="stat-sep">{t("plan.summary.at_reading")}</small>}
            <Rows
              lines={card.lines.map((key) => atReading.get(key)).filter((l): l is CardLine => l !== undefined)}
              capacity={view.battery_capacity_kwh}
              labels={card.lines.length > 1}
            />
            {day.size > 0 && (
              <>
                <small className="stat-sep">{t("plan.summary.day")}</small>
                <Rows
                  lines={card.lines.map((key) => day.get(key)).filter((l): l is CardLine => l !== undefined)}
                  capacity={view.battery_capacity_kwh}
                  labels={card.lines.length > 1}
                />
              </>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
