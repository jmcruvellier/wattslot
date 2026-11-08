// Courbe d'une ressource sur les dernières 24 h (un point par minute), en SVG sans bibliothèque :
// la page d'état reste légère. Le SVG s'étire sur la largeur à hauteur fixe ; les textes restent en
// HTML, à la taille de la page. Une ligne en pointillés marque chaque seuil d'alerte, nommé dans la
// légende (rouge, ou orange pour un second seuil). Le
// survol (ou le toucher) montre l'heure et la valeur du point le plus proche ; un trou dans les
// relevés (redémarrage) coupe la courbe.

import { useState, type PointerEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { zoned } from "../i18n/homeTime";
import { niceMax } from "./format";

// Seuil d'alerte : sa valeur, son texte de légende (« seuil d'alerte : … » par défaut) et sa
// couleur ; sans valeur, ou nulle, il n'est pas tracé.
export interface Threshold {
  value: number | null | undefined;
  text?: string;
  warning?: boolean;
}

export interface ChartPoint {
  time: number; // millisecondes
  value: number | null;
}

// Repère du SVG, étiré par le CSS : les traits gardent leur épaisseur (vector-effect).
const WIDTH = 1000;
const HEIGHT = 100;
const GAP_MS = 3 * 60_000; // au-delà, deux relevés ne se suivent pas

type Known = { time: number; value: number };

export default function ResourceChart({ points, format, label, thresholds = [] }: {
  points: ChartPoint[];
  format: (value: number) => string;
  label: string;
  thresholds?: Threshold[];
}) {
  const { language, t } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const known = points.filter((p): p is Known => p.value !== null);
  if (known.length < 2) return <p className="ui-row-help resource-chart-empty">{t("diagnostic.resources.chart_empty")}</p>;

  const start = known[0].time;
  const end = known[known.length - 1].time;
  // Haut de l'axe au-dessus des valeurs et du seuil : la ligne rouge reste visible.
  const lines = thresholds.filter((s): s is Threshold & { value: number } => s.value != null && s.value > 0);
  const top = niceMax(Math.max(...known.map((p) => p.value), ...lines.map((s) => s.value)));
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
  const line = (segment: Known[]) =>
    segment.map((p, i) => `${i ? "L" : "M"}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
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

  return (
    <figure className="resource-chart">
      <figcaption className="ui-row-help">
        {shown
          ? t("diagnostic.resources.chart_point", { time: clock(shown.time), value: format(shown.value) })
          : t("diagnostic.resources.chart_range", { start: clock(start), end: clock(end), top: format(top) })}
        {lines.map((line) => (
          <span key={line.text ?? "threshold"}>
            {" · "}
            <span className={line.warning ? "resource-chart-threshold-text warning" : "resource-chart-threshold-text"}>
              {t(line.text ?? "diagnostic.resources.chart_threshold", { value: format(line.value) })}
            </span>
          </span>
        ))}
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
          {lines.map((line) => (
            <line
              key={line.text ?? "threshold"}
              className={line.warning ? "resource-chart-threshold warning" : "resource-chart-threshold"}
              x1={0}
              x2={WIDTH}
              y1={y(line.value)}
              y2={y(line.value)}
            />
          ))}
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
