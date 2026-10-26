// Graphiques des vues de jour (lots 5.2 et 5.3) et de la semaine (lot 5.4), chargés à la demande (Recharts, point n° 2 de la
// phase 5) : prévu en pointillés, réel en trait plein, ligne du dernier relevé, heures creuses en
// bandes de fond — les conventions du dashboard de la v1.

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useI18n } from "../i18n/I18nProvider";
import { axisTick, hour, kwh, percent } from "./format";
import { useChartLegends } from "./legends";
import type { HourPoint, WeekPoint } from "./types";

interface ChartProps {
  hours: HourPoint[];
  readingHour: number | null;
}

// Couleurs du thème (lot 6b.1) : info-bulles, graduations et légendes suivent le thème affiché.
const TOOLTIP = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "0.75rem",
  color: "var(--text)",
};
const TICK = { fill: "var(--text-dim)", fontSize: 12 };
const LEGEND = { color: "var(--text)" };
// Pas de marge à gauche : l'axe des ordonnées prend la largeur de ses graduations (`width="auto"`).
const MARGIN = { top: 8, right: 8, bottom: 0, left: 0 };
// Libellé du plancher de la batterie au bord droit, au-dessus de la ligne, hors de la courbe.
const FLOOR_LABEL = { position: "insideTopRight", fill: "var(--discharge)", fontSize: 12 } as const;

/** Plages d'heures creuses [début, fin], en bandes de fond. */
function offPeakRanges(hours: HourPoint[]): [number, number][] {
  const ranges: [number, number][] = [];
  for (const point of hours) {
    if (!point.off_peak) continue;
    const last = ranges[ranges.length - 1];
    if (last && last[1] === point.hour) last[1] = point.hour + 1;
    else ranges.push([point.hour, point.hour + 1]);
  }
  return ranges;
}

// Axe des abscisses de minuit à minuit (numérique) : la 24e heure (23 h–24 h) est visible,
// contrairement à l'axe par catégories de Recharts qui plaçait le point « 23 h » au milieu
// de sa bande et laissait la fin de journée vide.
const DAY_TICKS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24];

function axes() {
  return [
    <CartesianGrid key="grid" stroke="var(--border)" strokeDasharray="2 4" />,
    // Graduations régulières (lot 7.1) : une sur deux, de 0 h à 24 h.
    <XAxis
      key="x"
      tick={TICK}
      dataKey="x"
      type="number"
      domain={[0, 24]}
      ticks={DAY_TICKS}
      tickFormatter={(x: number) => `${x}h`}
      stroke="var(--text-dim)"
    />,
  ];
}

export function EnergyChart({ hours, readingHour }: ChartProps) {
  const { t } = useI18n();
  const [legends] = useChartLegends();
  // Chaque point est l'énergie d'une heure : posée au milieu de la tranche (h + 0,5).
  const data = hours.map((h) => ({
    x: h.hour + 0.5,
    production: h.production_kwh,
    consumption: h.consumption_kwh,
    productionActual: h.production_actual_kwh,
    consumptionActual: h.consumption_actual_kwh,
  }));
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={MARGIN}>
          {axes()}
          <YAxis tick={TICK} stroke="var(--text-dim)" tickFormatter={axisTick("kWh")} width="auto" />
          <Tooltip contentStyle={TOOLTIP} labelFormatter={(x) => `${Math.floor(Number(x))}h`} formatter={(v) => `${kwh(Number(v))} kWh`} />
          {legends && <Legend wrapperStyle={LEGEND} />}
          <Line type="monotone" dataKey="production" name={t("plan.series.production")} stroke="var(--production)" strokeDasharray="5 4" dot={false} />
          <Line type="monotone" dataKey="productionActual" name={t("plan.series.production_actual")} stroke="var(--production)" dot={false} />
          <Line type="monotone" dataKey="consumption" name={t("plan.series.consumption")} stroke="var(--consumption)" strokeDasharray="5 4" dot={false} />
          <Line type="monotone" dataKey="consumptionActual" name={t("plan.series.consumption_actual")} stroke="var(--consumption)" dot={false} />
          {readingHour !== null && <ReferenceLine x={readingHour} stroke="var(--text-dim)" />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SocChart({ hours, readingHour, floor }: ChartProps & { floor: number | null }) {
  const { t } = useI18n();
  const [legends] = useChartLegends();
  // Le SoC d'une heure est celui de fin d'heure (modèle du backend) : posé à l'instant h + 1,
  // le point « 23 h » est donc le SoC atteint à minuit.
  const data = hours.map((h) => ({ x: h.hour + 1, soc: h.soc_percent, socActual: h.soc_actual_percent }));
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={MARGIN}>
          {offPeakRanges(hours).map(([start, end]) => (
            <ReferenceArea key={start} x1={start} x2={end} fill="var(--grid-import)" fillOpacity={0.08} />
          ))}
          {axes()}
          <YAxis tick={TICK} stroke="var(--text-dim)" tickFormatter={axisTick("%")} domain={[0, 100]} width="auto" />
          <Tooltip contentStyle={TOOLTIP} labelFormatter={(x) => `${Number(x)}h`} formatter={(v) => `${percent(Number(v))} %`} />
          {legends && <Legend wrapperStyle={LEGEND} />}
          <Line type="monotone" dataKey="soc" name={t("plan.series.soc")} stroke="var(--battery)" strokeDasharray="5 4" dot={false} />
          <Line type="monotone" dataKey="socActual" name={t("plan.series.soc_actual")} stroke="var(--battery)" dot={false} />
          {floor !== null && (
            <ReferenceLine y={floor} stroke="var(--discharge)" strokeDasharray="3 3" label={{ ...FLOOR_LABEL, value: t("plan.series.floor", { pct: floor }) }} />
          )}
          {readingHour !== null && <ReferenceLine x={readingHour} stroke="var(--text-dim)" />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function GridChart({ hours, readingHour }: ChartProps) {
  const { t } = useI18n();
  const [legends] = useChartLegends();
  // Achat au-dessus de zéro, surplus en dessous ; prévu en ligne (achat moins surplus).
  // Comme le graphe de production, chaque heure est posée au milieu de sa tranche.
  const data = hours.map((h) => ({
    x: h.hour + 0.5,
    net: Math.round((h.grid_import_kwh - h.grid_export_kwh) * 1000) / 1000,
    importActual: h.grid_import_actual_kwh,
    exportActual: h.grid_export_actual_kwh === null ? null : -h.grid_export_actual_kwh,
    offPeak: h.off_peak,
  }));
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={MARGIN} stackOffset="sign">
          {axes()}
          <YAxis tick={TICK} stroke="var(--text-dim)" tickFormatter={axisTick("kWh")} width="auto" />
          <Tooltip contentStyle={TOOLTIP} labelFormatter={(x) => `${Math.floor(Number(x))}h`} formatter={(v) => `${kwh(Math.abs(Number(v)))} kWh`} />
          {legends && <Legend wrapperStyle={LEGEND} />}
          <Bar dataKey="importActual" name={t("plan.series.import_actual")} stackId="actual" fill="var(--grid-import)">
            {data.map((point) => (
              <Cell key={point.x} fill={point.offPeak ? "var(--grid-import)" : "var(--grid-import-peak)"} />
            ))}
          </Bar>
          <Bar dataKey="exportActual" name={t("plan.series.export_actual")} stackId="actual" fill="var(--grid-export)" />
          <Line type="monotone" dataKey="net" name={t("plan.series.grid")} stroke="var(--text-dim)" strokeDasharray="5 4" dot={false} />
          <ReferenceLine y={0} stroke="var(--border)" />
          {readingHour !== null && <ReferenceLine x={readingHour} stroke="var(--text-dim)" />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export type WeekSeries = "production" | "consumption" | "soc";

const WEEK_COLORS: Record<WeekSeries, string> = {
  production: "var(--production)",
  consumption: "var(--consumption)",
  soc: "var(--battery)",
};

/** Plages d'indices [début, fin] consécutives où ``flags`` est vrai. */
function indexRanges(flags: boolean[]): [number, number][] {
  const ranges: [number, number][] = [];
  flags.forEach((flag, index) => {
    if (!flag) return;
    const last = ranges[ranges.length - 1];
    if (last && last[1] === index - 1) last[1] = index;
    else ranges.push([index, index]);
  });
  return ranges;
}

/** Écran étroit : numéro du jour seul en graduation, les noms se chevaucheraient. */
function useNarrow(): boolean {
  const query = "(max-width: 32rem)";
  const [narrow, setNarrow] = useState(() => typeof window.matchMedia === "function" && window.matchMedia(query).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = () => setNarrow(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return narrow;
}

/** Un graphique de la semaine (comme `dashboard_semaine.py`) : les heures des jours bout à bout,
 * un séparateur à chaque minuit, la ligne du dernier relevé ; heures creuses en fond pour la
 * consommation et le SoC, plancher de la batterie pour le SoC. */
export function WeekChart({
  points,
  series,
  nowIndex,
  floor,
}: {
  points: WeekPoint[];
  series: WeekSeries;
  nowIndex: number | null;
  floor: number;
}) {
  const { language, t } = useI18n();
  const narrow = useNarrow();
  const lang = language === "fr" ? "fr" : "en";
  const dayName = (iso: string, options: Intl.DateTimeFormatOptions) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString(language, options);
  const data = points.map((point, index) => ({
    index,
    value: series === "production" ? point.production_kwh : series === "consumption" ? point.consumption_kwh : point.soc_percent,
    surplus: series === "production" ? Math.round((point.production_kwh - point.consumption_kwh) * 1000) / 1000 : undefined,
    soc_kwh: point.soc_kwh,
  }));
  const ticks = points.flatMap((point, index) => (point.hour === 12 ? [index] : []));
  const midnights = points.flatMap((point, index) => (point.hour === 0 && index > 0 ? [index - 0.5] : []));
  const label = (index: number) => {
    const point = points[Math.round(index)];
    if (!point) return "";
    return `${dayName(point.day, { weekday: "long", day: "numeric" })} · ${hour(point.hour, lang)}–${hour(point.hour + 1, lang)}`;
  };
  const tick = (index: number) => {
    const point = points[index];
    if (!point) return "";
    return narrow ? dayName(point.day, { day: "numeric" }) : dayName(point.day, { weekday: "long", day: "numeric" });
  };
  const soc = series === "soc";
  const color = WEEK_COLORS[series];
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={MARGIN}>
          {series !== "production" &&
            indexRanges(points.map((point) => point.off_peak)).map(([start, end]) => (
              <ReferenceArea key={start} x1={start - 0.5} x2={end + 0.5} fill="var(--grid-import)" fillOpacity={0.1} />
            ))}
          <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" vertical={false} />
          <XAxis
            tick={TICK}
            dataKey="index"
            type="number"
            domain={[-0.5, points.length - 0.5]}
            ticks={ticks}
            tickFormatter={tick}
            stroke="var(--text-dim)"
            interval={0}
          />
          <YAxis
            tick={TICK}
            stroke="var(--text-dim)"
            tickFormatter={axisTick(soc ? "%" : "kWh")}
            domain={soc ? [0, 100] : [0, "auto"]}
            width="auto"
          />
          {series === "production" && <YAxis yAxisId="surplus" hide />}
          <Tooltip
            contentStyle={TOOLTIP}
            labelFormatter={(index) => label(Number(index))}
            formatter={(value, _name, item) =>
              soc
                ? `${percent(Number(value))} % (${kwh(Number((item.payload as { soc_kwh: number | null }).soc_kwh ?? 0))} kWh)`
                : `${kwh(Number(value))} kWh`
            }
          />
          {midnights.map((x) => (
            <ReferenceLine key={x} x={x} stroke="var(--border)" />
          ))}
          {soc && (
            <ReferenceLine y={floor} stroke="var(--discharge)" strokeDasharray="4 4" label={{ ...FLOOR_LABEL, value: t("plan.series.floor", { pct: floor }) }} />
          )}
          {nowIndex !== null && <ReferenceLine x={nowIndex} stroke="var(--text-dim)" strokeWidth={1.5} />}
          <Area
            dataKey="value"
            name={t(`plan.week.series.${series}`)}
            type="monotone"
            stroke={color}
            fill={color}
            fillOpacity={0.12}
            strokeDasharray="6 4"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          {series === "production" && (
            // Surplus (souvent négatif : production moins consommation) pour l'infobulle seulement,
            // sur son propre axe caché : l'axe de la production reste à partir de 0.
            <Area yAxisId="surplus" type="monotone" dataKey="surplus" name={t("plan.week.series.surplus")} stroke="none" fill="none" legendType="none" activeDot={false} />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
