// Menu latéral replié ou ouvert (lot 6b.2, point n° 7 de la phase 6 bis) : ouvert par défaut
// au-delà de 1 280 px, replié en dessous ; le choix de l'utilisateur est gardé par navigateur.

import { useCallback, useState } from "react";

export const MENU_STORAGE_KEY = "wattslot.menu";
export const WIDE_SCREEN_PX = 1280;

export function readCollapsed(width: number = window.innerWidth): boolean {
  try {
    const stored = window.localStorage.getItem(MENU_STORAGE_KEY);
    if (stored === "collapsed") return true;
    if (stored === "open") return false;
  } catch {
    // Stockage indisponible : réglage par défaut selon la largeur.
  }
  return width < WIDE_SCREEN_PX;
}

export function useMenuCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => readCollapsed());
  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(MENU_STORAGE_KEY, next ? "collapsed" : "open");
      } catch {
        // Stockage indisponible : le choix vaut pour la session seulement.
      }
      return next;
    });
  }, []);
  return [collapsed, toggle];
}
