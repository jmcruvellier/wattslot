// Section Courbes : les cartes et les graphiques de la phase 5 (chiffres du jour, frise, courbes
// de la batterie, du réseau et de l'énergie ; cartes des jours et courbes de la semaine), sortis
// de la section Planning, avec le panneau « Personnaliser » (lot 5.5). Mêmes onglets que
// Planning ; « Pourquoi ce plan » et les indicateurs restent dans Planning.

import { useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import DayCards from "./DayCards";
import { availableDayCards, availableIndicators, availableWeekCards, type CardId, type DayCardId } from "./layout";
import LayoutEditor from "./LayoutEditor";
import { LoadMessage, PlanTabs } from "./PlanTabs";
import { useDashboardLayout, usePlanView } from "./planView";
import type { DayView } from "./types";
import { WeekDetails } from "./WeekScreen";

// Cartes affichées dans Planning, à côté de l'agenda : pas ici.
const IN_PLANNING: DayCardId[] = ["indicators", "explanations"];

function curveCards(view: DayView): DayCardId[] {
  return availableDayCards(view).filter((id) => !IN_PLANNING.includes(id));
}

export default function CurvesScreen() {
  const { t } = useI18n();
  const { tab, load, open, retry } = usePlanView();
  const { layout, saving, failed, change, reset } = useDashboardLayout();
  const [editing, setEditing] = useState(false);

  // Cartes de la vue ouverte, que « Personnaliser » range ou masque.
  const available: CardId[] =
    load.status === "day" ? curveCards(load.view) : load.status === "week" ? availableWeekCards(load.view) : [];
  const loaded = load.status === "day" || load.status === "week";

  return (
    <section aria-labelledby="curves-title">
      {/* Le titre de la section est dans la barre du haut (lot 6b.2). */}
      <h2 id="curves-title" className="visually-hidden">
        {t("nav.curves")}
      </h2>
      {/* Onglets à gauche, « Personnaliser » à droite ; dessous quand la ligne est trop étroite. */}
      <div className="view-toolbar">
        <PlanTabs title={t("nav.curves")} tab={tab} onOpen={open} />
        {loaded && (
          <button type="button" aria-pressed={editing} onClick={() => setEditing(!editing)}>
            {t("plan.layout.open")}
          </button>
        )}
      </div>
      <LoadMessage load={load} tab={tab} onRetry={retry} />
      {loaded && editing && (
        <LayoutEditor
          kind={tab}
          layout={layout}
          available={available}
          indicators={load.status === "day" ? availableIndicators(load.view) : []}
          saving={saving}
          failed={failed}
          onChange={change}
          onReset={reset}
          onClose={() => setEditing(false)}
        />
      )}

      {load.status === "day" && (
        <DayCards view={load.view} layout={layout[load.view.kind]} indicators={layout.indicators} available={curveCards(load.view)} />
      )}
      {load.status === "week" && <WeekDetails view={load.view} onOpen={open} layout={layout.week} />}
    </section>
  );
}
