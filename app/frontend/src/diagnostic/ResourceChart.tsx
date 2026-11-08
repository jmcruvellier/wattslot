// Courbe d'une ressource sur les dernières 24 h (un point par minute), en SVG sans bibliothèque :
// la page d'état reste légère. Le SVG s'étire sur la largeur à hauteur fixe ; les textes restent en
// HTML, à la taille de la page. Une ligne rouge marque le seuil d'alerte quand il y en a un, vers
// 80 % de la hauteur ; la courbe est lissée sans dépasser les relevés (``smoothPath``). Le
// survol (ou le toucher) montre l'heure et la valeur du point le plus proche ; un trou dans les
// relevés (redémarrage) coupe la courbe.

import { useState, type PointerEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { zoned } from "../i18n/homeTime";
import { smoothPath } from "./chartPath";
import { axisTop } from "./format";

export interface ChartPoint {
  time: number; // millisecondes
  value: number | null;
}

// Repère du SVG, étiré par le CSS : les traits gardent leur épaisseur (vector-effect).
const WIDTH = 1000;
const HEIGHT = 100;
const GAP_MS = 3 * 60_000; // au-delà, deux relevés ne se suivent pas

type Known = { time: number; value: number };

export default function ResourceChart({ points, format, label, threshold }: {
  points: ChartPoint[];
  format: (value: number) => string;
  label: string;
  threshold?: number | null; // seuil d'alerte (ligne rouge)
}) {
  const { language, t } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const known = points.filter((p): p is Known => p.value !== null);
  if (known.length < 2) return <p className="ui-row-help resource-chart-empty">{t("diagnostic.resources.chart_empty")}</p>;

  const start = known[0].time;
  const end = known[known.length - 1].time;
  // Seuil vers 80 % de la hauteur : la marge qui reste se lit d'un coup d'œil.
  const top = axisTop(Math.max(...known.map((p) => p.value)), threshold);
  const x = (time: number) => ((time - start) / Math.max(end - start, 1)) * WIDTH;
  const y = (value: number) => (1 - Math.min(value, top) / top) * HEIGHT;
  const clock = (time: number) =>
    new Date(time).toLocaleTimeString(language, { ...zoned(), hour: "2-digit", minute: "2-digit" });

  // Segments continus, coupés aux trous.
  const segments: Known[][] = [];
  for (const point of known) {
    const last = segments[segments.length - 1];
    if (last && point.time - last[last.length - 1].time <= GAP_MS) last.push(point);
    else segments.push([point]);
  }
  const line = (segment: Known[]) => smoothPath(segment.map((p) => [x(p.time), y(p.value)]));
  const area = (segment: Known[]) =>
    `${line(segment)}L${x(segment[segment.length - 1].time).toFixed(1)},${HEIGHT}L${x(segment[0].time).toFixed(1)},${HEIGHT}Z`;

  const onMove = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const time = start + ((event.clientX - box.left) / box.width) * (end - start);
    let nearest = 0;
    known.forEach((p, i) => {
      if (Math.abs(p.time - time) < Math.abs(known[nearest].time - time)) nearest = i;
    });
    setHover(nearest);
  };
  const shown = hover === null ? null : known[hover];
  const shownThreshold = threshold != null && threshold <= top ? threshold : null;

  return (
    <figure className="resource-chart">
      <figcaption className="ui-row-help">
        {shown
          ? t("diagnostic.resources.chart_point", { time: clock(shown.time), value: format(shown.value) })
          : t("diagnostic.resources.chart_range", { start: clock(start), end: clock(end), top: format(top) })}
        {shownThreshold !== null && (
          <>
            {" · "}
            <span className="resource-chart-threshold-text">
              {t("diagnostic.resources.chart_threshold", { value: format(shownThreshold) })}
            </span>
          </>
        )}
      </figcaption>
      <div className="resource-chart-plot" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label={label}>
          <line className="resource-chart-grid" x1={0} x2={WIDTH} y1={0.5} y2={0.5} />
          {segments.map((segment) => (
            <g key={segment[0].time}>
              <path className="resource-chart-area" d={area(segment)} />
              <path className="resource-chart-line" d={line(segment)} />
            </g>
          ))}
          {shownThreshold !== null && (
            <line
              className="resource-chart-threshold"
              x1={0}
              x2={WIDTH}
              y1={y(shownThreshold)}
              y2={y(shownThreshold)}
            />
          )}
          <line className="resource-chart-axis" x1={0} x2={WIDTH} y1={HEIGHT - 0.5} y2={HEIGHT - 0.5} />
          {shown && <line className="resource-chart-cursor" x1={x(shown.time)} x2={x(shown.time)} y1={0} y2={HEIGHT} />}
        </svg>
        {shown && (
          <span
            className="resource-chart-dot"
            style={{ left: `${(x(shown.time) / WIDTH) * 100}%`, top: `${(y(shown.value) / HEIGHT) * 100}%` }}
          />
        )}
      </div>
      <div className="resource-chart-times ui-row-help">
        <span>{clock(start)}</span>
        <span>{clock(end)}</span>
      </div>
    </figure>
  );
}
