// Avertissements du plan qui disent qu'un appareil demandé n'est pas placé : montrés aussi sur
// « Aujourd'hui ». Ils n'apparaissaient que sur la page Planning, et un appareil non placé
// n'a ni bloc dans la frise ni « Prochaine action » : rien ne le signalait (20/11/2026).

import type { Notice } from "./types";

const UNPLACED = ["profil_indisponible_", "heures_insuffisantes_", "dependance_non_placee", "contrainte_impossible"];

/** Notices d'un appareil que le calcul n'a pas placé (codes des avertissements du serveur). */
export function unplacedNotices(notices: Notice[] | undefined): Notice[] {
  return (notices ?? []).filter((notice) => !notice.info && UNPLACED.some((code) => notice.code.startsWith(code)));
}
