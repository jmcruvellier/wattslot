// Montre un élément de la page par son identifiant (lot 6b.5) : déplie les sections repliées
// (<details>) qui le contiennent, puis fait défiler jusqu'à lui. Renvoie false s'il n'existe pas
// (encore).

export function reveal(id: string): boolean {
  const element = document.getElementById(id);
  if (!element) return false;
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (parent instanceof HTMLDetailsElement) parent.open = true;
  }
  element.scrollIntoView?.({ behavior: "smooth", block: "start" });
  return true;
}
