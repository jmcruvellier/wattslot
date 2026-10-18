// Choix du thème (lot 6b.1, points n° 5 et 6 de la phase 6 bis) : gardé dans le navigateur, sur
// chaque appareil ; « Automatique » en l'absence de choix, qui suit le réglage clair ou sombre du
// système (themes.css). Le script en ligne d'index.html applique le choix avant le premier
// affichage, avec la même clé et la même liste.

import { useCallback, useState } from "react";

export const THEMES = ["auto", "ivory", "graphite", "ocean", "meadow", "dusk"] as const;
export type Theme = (typeof THEMES)[number];

export const THEME_STORAGE_KEY = "wattslot.theme";

function isTheme(value: string | null): value is Theme {
  return (THEMES as readonly (string | null)[]).includes(value);
}

export function readTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : "auto";
  } catch {
    return "auto";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

function storeTheme(theme: Theme): void {
  try {
    if (theme === "auto") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Stockage indisponible (navigation privée) : le choix vaut pour la session seulement.
  }
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme);
  const setTheme = useCallback((next: Theme) => {
    storeTheme(next);
    applyTheme(next);
    setThemeState(next);
  }, []);
  return [theme, setTheme];
}
