// Cartes d'une vue de jour : celles que l'installation et le plan justifient (lot 5.3,
// `availableDayCards`), dans l'ordre et sans les cartes masquées de la disposition (lot 5.5).

import { Fragment, type ReactNode, Suspense } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { ExplanationsCard, IndicatorsCard } from "./InsightCards";
import { availableDayCards, type DayCardId, type IndicatorLayout, shownCards, type ViewLayout } from "./layout";
import { EnergyChart, GridChart, SocChart } from "./lazyCharts";
import SummaryCards from "./SummaryCards";
import TimelineCard from "./TimelineCard";
import type { DayView } from "./types";
import Icon from "../ui/Icon";
import type { IconName } from "../ui/iconPaths";



function readingHour(view: DayView): number | null {
  if (!view.actual_updated_at || view.kind !== "today") return null;
  const moment = new Date(view.actual_updated_at);
  return moment.getHours() + moment.getMinutes() / 60;
}

function ChartCard({ label, icon, wide, children }: { label: string; icon: IconName; wide?: boolean; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <article className={wide ? "card card-wide" : "card"} aria-label={label}>
      <h3>
        <Icon name={icon} size={20} /> {label}
      </h3>
      <Suspense fallback={<p>{t("plan.loading")}</p>}>{children}</Suspense>
    </article>
  );
}

function useRenderers(indicators: IndicatorLayout): Record<DayCardId, (view: DayView) => ReactNode> {
  const { t } = useI18n();
  return {
    summary: (view) => <SummaryCards view={view} />,
    timeline: (view) => <TimelineCard timeline={view.timeline} readingHour={readingHour(view)} />,
    soc: (view) => (
      <ChartCard label={t("plan.cards.soc")} icon="battery">
        <SocChart hours={view.hours} readingHour={readingHour(view)} floor={view.battery_floor_percent} />
      </ChartCard>
    ),
    grid: (view) => (
      <ChartCard label={t("plan.cards.grid")} icon="plug">
        <GridChart hours={view.hours} readingHour={readingHour(view)} />
      </ChartCard>
    ),
    energy: (view) => (
      <ChartCard label={t("plan.cards.energy")} icon="today" wide>
        <EnergyChart hours={view.hours} readingHour={readingHour(view)} />
      </ChartCard>
    ),
    indicators: (view) => <IndicatorsCard view={view} layout={indicators} />,
    explanations: (view) => <ExplanationsCard view={view} />,
  };
}

export default function DayCards({
  view,
  layout,
  indicators,
  available = availableDayCards(view),
}: {
  view: DayView;
  layout: ViewLayout;
  indicators: IndicatorLayout;
  available?: DayCardId[]; // par défaut, toutes celles que le plan justifie
}) {
  const render = useRenderers(indicators);
  // Le résumé est un groupe de cartes à lui seul : les autres cartes se rangent dans des grilles
  // avant ou après lui.
  const segments: DayCardId[][] = [];
  for (const id of shownCards(layout, available)) {
    const last = segments[segments.length - 1];
    if (id !== "summary" && last && last[0] !== "summary") last.push(id);
    else segments.push([id]);
  }
  return (
    <div className="card-stack">
      {segments.map((segment) =>
        segment[0] === "summary" ? (
          <Fragment key="summary">{render.summary(view)}</Fragment>
        ) : (
          <div key={segment[0]} className="cards cards-fill">
            {segment.map((id) => (
              <Fragment key={id}>{render[id](view)}</Fragment>
            ))}
          </div>
        ),
      )}
    </div>
  );
}
