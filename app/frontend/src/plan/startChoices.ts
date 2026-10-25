// Départs encore à venir de chaque équipement du jour, lus dans les explications du plan : la
// frise (TimelineCard) les propose au clic sur un bloc prévu pas encore lancé, comme « Prochaine
// action » et « Pourquoi ce plan » (OtherStarts). Le choix enregistré ne vaut que pour le jour.

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

/** Départs encore à venir de chaque équipement du jour ; appareil sans explication ou sans
 * autre départ : rien, le bloc garde son simple rôle d'info-bulle. */
export function startChoices(view: DayView): Record<string, StartChoice> {
  const nowMin = nowMinute();
  const choices: Record<string, StartChoice> = {};
  for (const item of view.explanations) {
    if (!item.explanation) continue;
    choices[item.device] = {
      alternatives: (item.explanation.alternatives ?? [])
        .filter((other) => other.debut_min > nowMin)
        .map((other) => ({
          start_min: other.debut_min,
          cost_eur_delta: other.ecart_cout_eur,
          import_kwh_delta: other.ecart_soutirage_kwh,
        })),
      chosen: item.explanation.choisi ?? false,
    };
  }
  return choices;
}
