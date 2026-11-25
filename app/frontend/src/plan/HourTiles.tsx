// Tuiles de l'heure choisie sur la frise : panneaux, maison, batterie, achat au réseau. Chacune
// dit la valeur de l'heure (mesurée, à défaut prévue), son écart au prévu, et montre la courbe
// de la journée heure par heure avec l'heure choisie marquée — trait plein pour le mesuré,
// pointillé pour le prévu des heures à venir. Les données sont celles des heures du jour
// (`HourPoint`), déjà lues pour le fond de la frise.

import { useI18n } from "../i18n/I18nProvider";
import { kwh, percent } from "./format";
import type { HourPoint } from "./types";

const WIDTH = 120;
const HEIGHT = 28;
// Écart au prévu dit à partir de ce seuil (kWh) : en deçà, c'est le bruit de la prévision.
const GAP_KWH = 0.1;

type Metric = {
  key: "panels" | "home" | "battery" | "grid_buying";
  unit: "kWh" | "%";
  planned: (point: HourPoint) => number | null;
  actual: (point: HourPoint) => number | null;
  tone: string;
  // Plus que prévu : favorable (1), défavorable (-1), ou pas d'écart dit (0).
  more: 1 | -1 | 0;
};

const METRICS: Metric[] = [
  {
    key: "panels",
    unit: "kWh",
    planned: (point) => point.production_kwh,
    actual: (point) => point.production_actual_kwh,
    tone: "var(--sun)",
    more: 1,
  },
  {
    key: "home",
    unit: "kWh",
    planned: (point) => point.consumption_kwh,
    actual: (point) => point.consumption_actual_kwh,
    tone: "var(--text-dim)",
    more: -1,
  },
  {
    key: "battery",
    unit: "%",
    planned: (point) => point.soc_percent,
    actual: (point) => point.soc_actual_percent,
    tone: "var(--battery)",
    more: 0,
  },
  {
    key: "grid_buying",
    unit: "kWh",
    planned: (point) => point.grid_import_kwh,
    actual: (point) => point.grid_import_actual_kwh,
    tone: "var(--grid-import)",
    more: -1,
  },
];

export default function HourTiles({
  hours,
  zone,
  readingHour,
}: {
  hours: HourPoint[];
  zone: number;
  readingHour: number | null;
}) {
  const { t } = useI18n();
  const chosen = hours.find((point) => point.hour === zone);
  if (!chosen) return null;
  // Mesuré d'une heure : pas celui de l'heure en cours, encore partiel (comme `hourSun`).
  const current = readingHour === null ? null : Math.floor(readingHour);
  const measured = (metric: Metric, point: HourPoint) =>
    point.hour === current ? null : metric.actual(point);
  const sorted = [...hours].sort((a, b) => a.hour - b.hour);

  const tiles = METRICS.flatMap((metric) => {
    const values = sorted.map(
      (point) => measured(metric, point) ?? metric.planned(point),
    );
    // Maison sans panneaux ou sans batterie : pas de tuile vide.
    if (values.every((value) => value === null || value === 0)) return [];
    const top = Math.max(...values.map((value) => value ?? 0), 0.001);
    const points = sorted.map((point, index) => ({
      x: ((point.hour + 0.5) / 24) * WIDTH,
      y: HEIGHT - 2 - ((values[index] ?? 0) / top) * (HEIGHT - 6),
      measured: measured(metric, point) !== null,
    }));
    const path = (items: typeof points) =>
      items
        .map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`)
        .join(" ");
    const last = points.reduce(
      (found, point, index) => (point.measured ? index : found),
      -1,
    );
    const actual = measured(metric, chosen);
    const planned = metric.planned(chosen);
    const value = actual ?? planned;
    const gap = actual !== null && planned !== null ? actual - planned : 0;
    const shown = metric.more !== 0 && Math.round(Math.abs(gap) * 100) / 100 >= GAP_KWH;
    const text = (amount: number | null) =>
      metric.unit === "%" ? `${percent(amount)} %` : `${kwh(amount)} kWh`;
    return [
      <div key={metric.key} className="tl-tile">
        <small>{t(`today.now.${metric.key}`)}</small>
        <p>
          <strong>{text(value)}</strong>{" "}
          {actual === null && planned !== null && (
            <span className="dim">{t("plan.timeline.detail.planned")}</span>
          )}
          {shown && (
            <span
              className={gap * metric.more > 0 ? "tl-tile-good" : "tl-tile-bad"}
            >
              {gap > 0 ? "↑" : "↓"} {kwh(Math.abs(gap))}
            </span>
          )}
        </p>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="none"
          aria-hidden="true"
          style={{ color: metric.tone }}
        >
          <rect
            className="tl-tile-zone"
            x={(zone / 24) * WIDTH}
            y="0"
            width={WIDTH / 24}
            height={HEIGHT}
          />
          <polygon
            className="tl-tile-area"
            points={`0,${HEIGHT} ${path(points)} ${WIDTH},${HEIGHT}`}
          />
          {last >= 0 && (
            <polyline
              className="tl-tile-line"
              points={path(points.slice(0, last + 1))}
            />
          )}
          {last < points.length - 1 && (
            <polyline
              className="tl-tile-line tl-tile-planned"
              points={path(points.slice(Math.max(last, 0)))}
            />
          )}
        </svg>
      </div>,
    ];
  });
  if (tiles.length === 0) return null;
  return <div className="tl-tiles">{tiles}</div>;
}
