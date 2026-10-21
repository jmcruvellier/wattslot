// « Plan du jour », nouveau dashboard (lot 5.2, socle) : onglets Hier, Aujourd'hui, Demain et
// Semaine sur l'API des vues, actualisation quand un nouveau calcul arrive (`planView`).
// Section Planning (lot 6b.4) : chaque jour en agenda (`Agenda`), puis « Pourquoi ce plan » et
// les indicateurs du plan côte à côte. Les courbes et les cartes de la phase 5 sont dans la
// section Courbes (`CurvesScreen`). « Mes demandes » en bas, sous chaque onglet : ce que le plan
// doit placer, à côté de ce qu'il prévoit (déplacé depuis la page Assistant).

import { useI18n } from "../i18n/I18nProvider";
import RequestsSection from "../start/RequestsSection";
import Agenda, { DaySummaryCard } from "./Agenda";
import Banners from "./Banners";
import { ExplanationsCard, IndicatorsCard } from "./InsightCards";
import { availableDayCards } from "./layout";
import PlanActions from "./PlanActions";
import ProvisionalNote from "./ProvisionalNote";
import { LoadMessage, PlanTabs } from "./PlanTabs";
import { useDashboardLayout, usePlanView } from "./planView";
import ViewHeader from "./ViewHeader";
import WeekScreen from "./WeekScreen";

export { POLL_MS } from "./planView";

export default function PlanScreen() {
  const { t } = useI18n();
  const { tab, load, open, reload, retry } = usePlanView();
  // Indicateur mis en avant et indicateurs masqués, choisis dans « Personnaliser » (Courbes).
  const { layout } = useDashboardLayout();

  return (
    <section aria-labelledby="plan-title">
      {/* Le titre de la section est dans la barre du haut (lot 6b.2). */}
      <h2 id="plan-title" className="visually-hidden">
        {t("plan.title")}
      </h2>
      {/* Onglets à gauche, actions de la vue à droite ; dessous quand la ligne est trop étroite. */}
      <div className="view-toolbar">
        <PlanTabs title={t("plan.title")} tab={tab} onOpen={open} />
        {(load.status === "day" || load.status === "week") && <PlanActions key={tab} kind={tab} onChanged={reload} />}
      </div>
      <LoadMessage load={load} tab={tab} onRetry={retry} />

      {load.status === "day" && (
        <>
          <ViewHeader view={load.view} />
          <ProvisionalNote view={load.view} />
          <Banners view={load.view} />
          <div className="plan-agenda">
            <DaySummaryCard view={load.view} />
            <Agenda view={load.view} />
          </div>
          {/* Côte à côte quand la largeur le permet, l'un sous l'autre sur téléphone. */}
          <div className="plan-insights">
            {availableDayCards(load.view).includes("explanations") && (
              <ExplanationsCard view={load.view} onChanged={reload} />
            )}
            <IndicatorsCard view={load.view} layout={layout.indicators} />
          </div>
        </>
      )}

      {load.status === "week" && <WeekScreen view={load.view} onOpen={open} />}

      <div className="ui-card plan-requests">
        <RequestsSection />
      </div>
    </section>
  );
}
