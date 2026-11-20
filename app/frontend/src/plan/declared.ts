// « C'est lancé » (api/planning/launched) : l'appareil n'est plus à lancer aujourd'hui. Pour un
// cycle qui n'est pas le premier de la journée (« Sèche-linge #2 »), la déclaration change aussi
// le plan : elle sépare une seconde charge lancée derrière la première. Le mesuré se relit
// aussitôt, mais les blocs prévus gardaient ceux du dernier calcul jusqu'au suivant, parfois une
// heure (constaté le 20/11/2026) : un nouveau calcul est lancé aussitôt, comme pour un départ
// choisi. Pour un premier cycle, la déclaration ne change rien au plan : pas de calcul.

import { deleteRequest, postJson } from "../api";

/** La déclaration de ce cycle change-t-elle le plan : un cycle après le premier de la journée. */
function changesPlan(cycle: string): boolean {
  const rank = / #(\d+)$/.exec(cycle);
  return rank !== null && Number(rank[1]) >= 2;
}

export async function declareLaunched(cycle: string): Promise<void> {
  await postJson("api/planning/launched", { device: cycle });
  if (changesPlan(cycle)) await postJson("api/planning/run", {});
}

/** Retour en arrière : la charge n'est plus séparée, le plan se recalcule de même. */
export async function withdrawLaunched(cycle: string): Promise<void> {
  await deleteRequest(`api/planning/launched/${encodeURIComponent(cycle)}`);
  if (changesPlan(cycle)) await postJson("api/planning/run", {});
}
