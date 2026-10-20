// Adresses de l'interface (lot 6b.2) : une par section et par sous-page, après le « # » pour
// marcher derrière l'ingress de Home Assistant sans réglage du serveur. Le bouton « précédent »
// du navigateur revient à l'adresse d'avant ; un lien ouvre directement la bonne section.

import { useCallback, useEffect, useState } from "react";

export const SECTIONS = ["today", "planning", "curves", "home", "assistant", "settings"] as const;
export type Section = (typeof SECTIONS)[number];

// Sous-pages rangées sous une section (« Pour aller plus loin »).
export const SUBPAGES = {
  // Écrans experts de Ma maison (lot 6b.5).
  home: ["templates", "backup", "graph", "library"],
  // Sous-pages des Réglages (lot 6b.6), ouvertes depuis leur liste.
  settings: ["notifications", "voice", "display", "calculation", "status", "connection", "library"],
} as const satisfies Partial<Record<Section, readonly string[]>>;
export type Subpage =
  | "library"
  | "status"
  | "connection"
  | "templates"
  | "backup"
  | "graph"
  | "notifications"
  | "display"
  | "calculation"
  | "voice";

export type Route = { section: Section; sub: Subpage | null } | { section: "ui"; sub: null };

export const DEFAULT_ROUTE: Route = { section: "today", sub: null };

export function routeHash(route: Route): string {
  return route.sub ? `#/${route.section}/${route.sub}` : `#/${route.section}`;
}

export function parseHash(hash: string): Route | null {
  const [section, sub, ...rest] = hash.replace(/^#\/?/, "").split("/");
  if (rest.length > 0) return null;
  if (section === "ui" && !sub) return { section: "ui", sub: null };
  if (!(SECTIONS as readonly string[]).includes(section)) return null;
  if (!sub) return { section: section as Section, sub: null };
  const allowed: readonly string[] = SUBPAGES[section as keyof typeof SUBPAGES] ?? [];
  return allowed.includes(sub) ? { section: section as Section, sub: sub as Subpage } : null;
}

// Pages d'avant la phase 6 bis, encore citées par la mise en route et le diagnostic du serveur
// (« home#tariff », « settings#notification ») : leur nouvelle place.
const LEGACY: Record<string, Route> = {
  start: { section: "today", sub: null },
  dashboard: { section: "planning", sub: null },
  home: { section: "home", sub: null },
  library: { section: "home", sub: "library" },
  settings: { section: "settings", sub: null },
  assistant: { section: "assistant", sub: null },
  connection: { section: "settings", sub: "connection" },
  diagnostic: { section: "settings", sub: "status" },
  devices: { section: "home", sub: null }, // fiches des appareils, dans l'onglet « Appareils »
  templates: { section: "home", sub: "templates" },
  backup: { section: "home", sub: "backup" },
  graph: { section: "home", sub: "graph" },
};

// Ancres de Ma maison passées dans une sous-page (lot 6b.5) : « home#models » ouvre les modèles.
function settingsAnchorPage(anchor: string): Route | null {
  if (anchor === "notification" || anchor === "notifications") return { section: "settings", sub: "notifications" };
  if (["tasks", "forecast", "scheduler"].includes(anchor)) return { section: "settings", sub: "calculation" };
  if (anchor === "appearance") return { section: "settings", sub: "display" };
  return null;
}

function homeAnchorPage(anchor: string): Route | null {
  if (anchor === "models") return { section: "home", sub: "templates" };
  return null;
}

/** Cible d'un lien du serveur (ancienne page ou adresse) : route et ancre éventuelle. */
export function resolveTarget(target: string): { route: Route; anchor: string | null } | null {
  if (target.startsWith("#/")) {
    const route = parseHash(target);
    return route ? { route, anchor: null } : null;
  }
  const [page, anchor] = target.split("#");
  const route = LEGACY[page];
  if (!route) return null;
  const moved =
    anchor && page === "home" ? homeAnchorPage(anchor) : anchor && page === "settings" ? settingsAnchorPage(anchor) : null;
  return { route: moved ?? route, anchor: anchor || null };
}

/** Route ouverte, lue dans l'adresse ; `fallback` quand l'adresse n'en désigne aucune. */
export function useRoute(fallback: Route): [Route, (route: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash) ?? fallback);
  useEffect(() => {
    const onHash = () => setRoute(parseHash(window.location.hash) ?? fallback);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [fallback]);
  const navigate = useCallback((next: Route) => {
    // Une entrée d'historique par changement : « précédent » ramène à la route d'avant.
    window.location.hash = routeHash(next);
    setRoute(next);
  }, []);
  return [route, navigate];
}
