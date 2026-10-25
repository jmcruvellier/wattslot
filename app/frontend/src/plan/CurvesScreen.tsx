// Section Courbes : les cartes et les graphiques de la phase 5 (chiffres du jour, frise, courbes
// de la batterie, du réseau et de l'énergie ; cartes des jours et courbes de la semaine), sortis
// de la section Planning, avec le panneau « Personnaliser » (lot 5.5). Mêmes onglets que
// Planning ; « Pourquoi ce plan » et les indicateurs restent dans Planning. Le bouton
// « Personnaliser » est dans la barre de titre (App, `curvesEdit`) ; son panneau s'ouvre ici.

import { useEffect } from "react";

import { useI18n } from "../i18n/I18nProvider";
import DayCards from "./DayCards";
import { leaveCurves, setCurvesAvailable, setCurvesEditing, useCurvesEditing } from "./curvesEdit";
import { availableDayCards, availableIndicators, availableWeekCards, type CardId, type DayCardId } from "./layout";
import LayoutEditor from "./LayoutEditor";
import DiscardedNote from "./DiscardedNote";
import ProvisionalNote from "./ProvisionalNote";
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
  const { tab, load, open, reload, retry } = usePlanView();
  const { layout, saving, failed, change, reset } = useDashboardLayout();
  const { editing } = useCurvesEditing();

  // Cartes de la vue ouverte, que « Personnaliser » range ou masque.
  const available: CardId[] =
    load.status === "day" ? curveCards(load.view) : load.status === "week" ? availableWeekCards(load.view) : [];
  const loaded = load.status === "day" || load.status === "week";

  // Le bouton de la barre de titre n'apparaît qu'avec une vue ouverte ; quitter la section
  // referme le panneau, dont l'état vit hors de l'écran (curvesEdit).
  useEffect(() => {
    setCurvesAvailable(loaded);
  }, [loaded]);
  useEffect(() => leaveCurves, []);

  return (
    <section aria-labelledby="curves-title">
      {/* Le titre de la section est dans la barre du haut (lot 6b.2). */}
      <h2 id="curves-title" className="visually-hidden">
        {t("nav.curves")}
      </h2>
      {/* Onglets à gauche ; « Personnaliser » est dans la barre du haut, près de « Calculer ». */}
      <div className="view-toolbar">
        <PlanTabs title={t("nav.curves")} tab={tab} onOpen={open} />
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
          onClose={() => setCurvesEditing(false)}
        />
      )}

      {load.status === "day" && <DiscardedNote hours={load.view.discarded_hours ?? []} />}
      {load.status === "week" && <DiscardedNote hours={load.view.discarded_hours ?? []} />}
      {load.status === "day" && <ProvisionalNote view={load.view} />}
      {load.status === "day" && (
        /* « onChanged » : la frise du jour permet de changer un départ, la vue se relit. */
        <DayCards
          view={load.view}
          layout={layout[load.view.kind]}
          indicators={layout.indicators}
          available={curveCards(load.view)}
          onChanged={reload}
        />
      )}
      {load.status === "week" && <WeekDetails view={load.view} onOpen={open} layout={layout.week} />}
    </section>
  );
}
