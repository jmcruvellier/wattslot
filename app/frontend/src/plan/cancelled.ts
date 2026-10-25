// Annulation d'une planification pour aujourd'hui (api/planning/cancelled) : le calcul suivant
// ne place plus l'équipement, sa tâche reste dans la liste de Home Assistant (le calcul de demain
// la reprendra). « Rétablir » le rend au calcul. Comme pour un départ choisi, un nouveau calcul
// est lancé aussitôt, et la vue se relit.

import { deleteRequest, postJson } from "../api";

export async function cancelTask(device: string): Promise<void> {
  await postJson("api/planning/cancelled", { device });
  await postJson("api/planning/run", {}); // nouveau plan sans cet équipement
}

export async function restoreTask(device: string): Promise<void> {
  await deleteRequest(`api/planning/cancelled/${encodeURIComponent(device)}`);
  await postJson("api/planning/run", {});
}
