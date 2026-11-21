// Couleur d'un fonctionnement dans la frise, d'après le nom de sa vitesse (filtration de piscine) :
// silence, éco et boost ont chacun la leur. Le nom est celui que l'utilisateur a donné à la
// vitesse dans les réglages : lu sans majuscules ni accents (« Éco », « BOOST »). Une vitesse
// d'un autre nom, ou sans nom (aucune vitesse réglée), prend la couleur du silence.

const COLORS: Record<string, string> = {
  eco: "var(--pool-eco)",
  boost: "var(--pool-boost)",
};

export function modeColor(mode: string | null | undefined): string {
  const name = (mode ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim()
    .toLowerCase();
  return COLORS[name] ?? "var(--pool-silence)";
}
