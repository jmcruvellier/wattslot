// Légendes des courbes de la section Courbes : affichées ou masquées, réglées dans « Langue et
// affichage » (AppearanceSection) ; gardées dans le navigateur, sur chaque appareil, comme le
// thème. Rien de gardé vaut « affichées ».

import { useCallback, useState } from "react";

export const LEGENDS_STORAGE_KEY = "wattslot.legends";
const HIDDEN = "hide";

export function readChartLegends(): boolean {
  try {
    return window.localStorage.getItem(LEGENDS_STORAGE_KEY) !== HIDDEN;
  } catch {
    return true;
  }
}

function storeChartLegends(shown: boolean): void {
  try {
    if (shown) window.localStorage.removeItem(LEGENDS_STORAGE_KEY);
    else window.localStorage.setItem(LEGENDS_STORAGE_KEY, HIDDEN);
  } catch {
    // Stockage indisponible (navigation privée) : le choix vaut pour la session seulement.
  }
}

export function useChartLegends(): [boolean, (shown: boolean) => void] {
  const [legends, setLegendsState] = useState(readChartLegends);
  const setLegends = useCallback((next: boolean) => {
    storeChartLegends(next);
    setLegendsState(next);
  }, []);
  return [legends, setLegends];
}
