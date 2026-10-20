// Onglet ouvert de Ma maison, gardé dans le navigateur : partagé avec les liens d'autres écrans
// (« Voir les données » de Courbes ouvre l'onglet Données) sans charger Ma maison.

export const TAB_KEY = "home.tab";
export const TABS = ["essentials", "devices", "data", "more"] as const;
export type Tab = (typeof TABS)[number];

export function savedTab(): Tab {
  try {
    const found = window.localStorage.getItem(TAB_KEY);
    return (TABS as readonly string[]).includes(found ?? "") ? (found as Tab) : "essentials";
  } catch {
    return "essentials";
  }
}

export function rememberTab(tab: Tab) {
  try {
    window.localStorage.setItem(TAB_KEY, tab);
  } catch {
    // stockage indisponible : rien à garder
  }
}
