// Courbe d'une ressource sur les dernières 24 h (un point par minute), en SVG sans bibliothèque :
// la page d'état reste légère. Le survol (ou le toucher) montre l'heure et la valeur du point le
// plus proche ; un trou dans les relevés (redémarrage) coupe la courbe.

import { useState, type PointerEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { zoned } from "../i18n/homeTime";
import { niceMax } from "./format";

export interface ChartPoint {
  time: number; // millisecondes
  value: number | null;
}

const WIDTH = 600;
const HEIGHT = 150;
const PAD = { top: 10, right: 8, bottom: 20, left: 8 };
const GAP_MS = 3 * 60_000; // au-delà, deux relevés ne se suivent pas

export default function ResourceChart({ points, format, label, max }: {
  points: ChartPoint[];
  format: (value: number) => string;
  label: string;
  max?: number; // haut imposé (taille du disque) ; sinon d'après les valeurs
}) {
  const { language, t } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const known = points.filter((p): p is { time: number; value: number } => p.value !== null);
  if (known.length < 2) return <p className="ui-row-help resource-chart-empty">{t("diagnostic.resources.chart_empty")}</p>;

  const start = known[0].time;
  const end = known[known.length - 1].time;
  const top = max ?? niceMax(Math.max(...known.map((p) => p.value)));
  const x = (time: number) => PAD.left + ((time - start) / Math.max(end - start, 1)) * (WIDTH - PAD.left - PAD.right);
  const y = (value: number) => PAD.top + (1 - value / top) * (HEIGHT - PAD.top - PAD.bottom);
  const clock = (time: number) =>
    new Date(time).toLocaleTimeString(language, { ...zoned(), hour: "2-digit", minute: "2-digit" });

  // Segments continus, coupés aux trous.
  const segments: { time: number; value: number }[][] = [];
  for (const point of known) {
    const last = segments[segments.length - 1];
    if (last && point.time - last[last.length - 1].time <= GAP_MS) last.push(point);
    else segments.push([point]);
  }
  const line = (segment: { time: number; value: number }[]) =>
    segment.map((p, i) => `${i ? "L" : "M"}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const area = (segment: { time: number; value: number }[]) =>
    `${line(segment)}L${x(segment[segment.length - 1].time).toFixed(1)},${y(0)}L${x(segment[0].time).toFixed(1)},${y(0)}Z`;

  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const time = start + ((event.clientX - box.left) / box.width) * (end - start);
    let nearest = 0;
    known.forEach((p, i) => {
      if (Math.abs(p.time - time) < Math.abs(known[nearest].time - time)) nearest = i;
    });
    setHover(nearest);
  };
  const shown = hover === null ? null : known[hover];

  return (
    <figure className="resource-chart">
      <figcaption className="ui-row-help">
        {shown
          ? t("diagnostic.resources.chart_point", { time: clock(shown.time), value: format(shown.value) })
          : t("diagnostic.resources.chart_range", { start: clock(start), end: clock(end), top: format(top) })}
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={label}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <line className="resource-chart-axis" x1={PAD.left} x2={WIDTH - PAD.right} y1={y(0)} y2={y(0)} />
        <line className="resource-chart-grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y(top)} y2={y(top)} />
        {segments.map((segment) => (
          <g key={segment[0].time}>
            <path className="resource-chart-area" d={area(segment)} />
            <path className="resource-chart-line" d={line(segment)} />
          </g>
        ))}
        <text className="resource-chart-label" x={PAD.left} y={HEIGHT - 4}>
          {clock(start)}
        </text>
        <text className="resource-chart-label" x={WIDTH - PAD.right} y={HEIGHT - 4} textAnchor="end">
          {clock(end)}
        </text>
        {shown && (
          <>
            <line
              className="resource-chart-cursor"
              x1={x(shown.time)}
              x2={x(shown.time)}
              y1={PAD.top}
              y2={y(0)}
            />
            <circle className="resource-chart-dot" cx={x(shown.time)} cy={y(shown.value)} r={4} />
          </>
        )}
      </svg>
    </figure>
  );
}
