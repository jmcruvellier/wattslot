// Départs possibles et annulation de la planification, pour les équipements de la frise du jour
// (TimelineCard) : la feuille au clic sur un bloc prévu propose les autres départs encore à venir
// (comme « Prochaine action » et « Pourquoi ce plan », OtherStarts) et le bouton « Annuler ».
// Le choix vaut pour le jour du plan affiché (aujourd'hui, demain ou un jour suivant) ;
// l'annulation, pour aujourd'hui seulement.

import { minuteOfDay } from "../i18n/homeTime";
import type { OtherStart } from "./OtherStarts";
import type { DayView } from "./types";

/** Autres départs possibles d'un équipement de la frise : ceux que le plan propose encore, et
 * le départ que l'utilisateur a choisi (à annuler ou à changer). */
export interface StartChoice {
  alternatives: OtherStart[];
  chosen: boolean;
}

/** Minutes depuis minuit maintenant, comme l'agenda : les autres départs ne se proposent
 * qu'avant le départ prévu. */
function nowMinute(): number {
  return minuteOfDay();
}

/** Équipements d'un cycle de la frise du jour (appareils à lancer), avec leurs autres départs
 * encore à venir lus dans les explications du plan ; appareil sans explication : la feuille
 * propose seulement d'annuler la planification. */
export function startChoices(view: DayView): Record<string, StartChoice> {
  // Demain et les jours suivants : tous les départs proposés sont à venir.
  const nowMin = view.kind === "today" ? nowMinute() : -1;
  const explained = new Map(view.explanations.map((item) => [item.device, item]));
  const choices: Record<string, StartChoice> = {};
  for (const row of view.timeline.rows) {
    if (row.kind !== "cycle") continue;
    // Un équipement peut avoir plusieurs cycles dans la journée : chacun a ses propres départs,
    // sous son identité (celle de sa barre et de son explication).
    const cycles = row.planned.filter((bar) => !bar.carried).map((bar) => bar.cycle ?? row.device);
    for (const cycle of cycles.length > 0 ? cycles : [row.device]) {
      const explanation = explained.get(cycle)?.explanation;
      choices[cycle] = {
        alternatives: (explanation?.alternatives ?? [])
          .filter((other) => other.debut_min > nowMin)
          .map((other) => ({
            start_min: other.debut_min,
            cost_eur_delta: other.ecart_cout_eur,
            import_kwh_delta: other.ecart_soutirage_kwh,
          })),
        chosen: explanation?.choisi ?? false,
      };
    }
  }
  return choices;
}
