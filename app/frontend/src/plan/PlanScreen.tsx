// « Plan du jour », nouveau dashboard (lot 5.2, socle) : onglets Hier, Aujourd'hui, Demain et
// Semaine sur l'API des vues, actualisation quand un nouveau calcul arrive (`planView`).
// Section Planning (lot 6b.4) : chaque jour en agenda (`Agenda`, qui porte la raison de chaque
// créneau et « Pourquoi ce plan », dépliés à la demande), puis les indicateurs du plan ; sur
// un écran large, l'agenda à gauche, les indicateurs et « Mes demandes » à droite. Les courbes et les cartes de la phase 5 sont dans la
// section Courbes (`CurvesScreen`). « Mes demandes » en bas, sous chaque onglet : ce que le plan
// doit placer, à côté de ce qu'il prévoit (déplacé depuis la page Assistant).

import { useI18n } from "../i18n/I18nProvider";
import RequestsSection from "../start/RequestsSection";
import Agenda from "./Agenda";
import Banners from "./Banners";
import { IndicatorsCard } from "./InsightCards";
import BatteriesCard from "./BatteryList";
import PhasesCard from "./PhasesCard";
import { availableDayCards } from "./layout";
import DiscardedNote from "./DiscardedNote";
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

  // « Mes demandes » : celles du jour affiché ; toutes sous Semaine (ou tant que le jour n'est
  // pas lu). « Fait » et « C'est lancé » sous Hier et Aujourd'hui seulement : sous un jour à
  // venir (et la semaine), une demande ne peut pas avoir été faite, seulement annulée.
  const requests = (
    <RequestsSection
      future={tab !== "yesterday" && tab !== "today"}
      day={load.status === "day" ? load.view.day : undefined}
      today={tab === "today"}
      computedAt={load.status === "day" || load.status === "week" ? load.view.computed_at : null}
    />
  );

  return (
    <section aria-labelledby="plan-title">
      {/* Le titre de la section est dans la barre du haut (lot 6b.2). */}
      <h2 id="plan-title" className="visually-hidden">
        {t("plan.title")}
      </h2>
      {/* Onglets de la vue ouverte ; les actions sont dans la barre du haut (PlanActions). */}
      <div className="view-toolbar">
        <PlanTabs title={t("plan.title")} tab={tab} onOpen={open} />
      </div>
      <LoadMessage load={load} tab={tab} onRetry={retry} />

      {load.status === "day" && (
        <>
          <ViewHeader view={load.view} />
          <DiscardedNote hours={load.view.discarded_hours ?? []} />
          <ProvisionalNote view={load.view} />
          <Banners view={load.view} />
          {/* Deux colonnes sur un écran large, l'une sous l'autre sinon (styles.css). */}
          <div className="plan-columns">
            <div className="plan-agenda">
              <Agenda
                view={load.view}
                onChanged={reload}
                why={availableDayCards(load.view).includes("explanations")}
              />
            </div>
            <div className="plan-side">
              <div className="plan-insights">
                <IndicatorsCard view={load.view} layout={layout.indicators} compact all />
                <BatteriesCard view={load.view} />
                <PhasesCard view={load.view} />
              </div>
              {requests}
            </div>
          </div>
        </>
      )}

      {load.status === "week" && (
        <>
          {/* Mesures impossibles : celles du jour qui ouvre la semaine seulement. */}
          <DiscardedNote hours={load.view.discarded_hours ?? []} />
          <WeekScreen view={load.view} onOpen={open} side={requests} />
        </>
      )}

      {/* Plan pas encore lu, ou manquant : « Mes demandes » seul. */}
      {load.status !== "day" && load.status !== "week" && requests}
    </section>
  );
}
