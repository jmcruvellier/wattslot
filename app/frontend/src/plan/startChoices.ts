// Départs possibles et annulation de la planification, pour les équipements de la frise du jour
// (TimelineCard) : la feuille au clic sur un bloc prévu propose les autres départs encore à venir
// (comme « Prochaine action » et « Pourquoi ce plan », OtherStarts) et le bouton « Annuler ».
// Le choix et l'annulation enregistrés ne valent que pour le jour.

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
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

/** Équipements d'un cycle de la frise du jour (appareils à lancer), avec leurs autres départs
 * encore à venir lus dans les explications du plan ; appareil sans explication : la feuille
 * propose seulement d'annuler la planification. */
export function startChoices(view: DayView): Record<string, StartChoice> {
  const nowMin = nowMinute();
  const explained = new Map(view.explanations.map((item) => [item.device, item]));
  const choices: Record<string, StartChoice> = {};
  for (const row of view.timeline.rows) {
    if (row.kind !== "cycle") continue;
    const explanation = explained.get(row.device)?.explanation;
    choices[row.device] = {
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
  return choices;
}
