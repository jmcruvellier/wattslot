// Écran large : les blocs dépliables de Planning (tuiles du haut, « Pourquoi ce plan ») y sont
// dépliés d'emblée, la place ne manquant pas ; sur téléphone ils restent repliés pour ne pas
// allonger la page. Le chevron les replie ou les déplie dans les deux cas.

export function wideScreen(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(min-width: 52rem)").matches;
}
