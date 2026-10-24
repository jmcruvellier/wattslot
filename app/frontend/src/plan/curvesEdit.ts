// État du panneau « Personnaliser » de la section Courbes : son bouton vit dans la barre de
// titre (App.tsx, `PlanActions`), mais le panneau qu'il ouvre (`LayoutEditor`) est dans l'écran,
// chargé à la demande (`CurvesScreen`). Un petit magasin partagé relie les deux, plutôt que des
// props : l'écran dit quand une vue est ouverte, le bouton n'apparaît que là, et quitter la
// section referme le panneau.

import { useSyncExternalStore } from "react";

// editing : panneau ouvert ; available : une vue de Courbes est ouverte, le bouton peut se montrer.
const state = { editing: false, available: false };
const listeners = new Set<() => void>();

function publish(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** L'écran des courbes signale si une vue (jour ou semaine) est ouverte. */
export function setCurvesAvailable(next: boolean): void {
  if (state.available === next) return;
  state.available = next;
  publish();
}

/** Quitter la section Courbes referme le panneau : l'état vit hors de l'écran. */
export function leaveCurves(): void {
  state.editing = false;
  state.available = false;
  publish();
}

export function setCurvesEditing(next: boolean): void {
  state.editing = next;
  publish();
}

/** Panneau ouvert, et vue prête à se régler ; le bouton de la barre de titre s'y abonne. */
export function useCurvesEditing(): { editing: boolean; available: boolean } {
  const editing = useSyncExternalStore(subscribe, () => state.editing);
  const available = useSyncExternalStore(subscribe, () => state.available);
  return { editing, available };
}
