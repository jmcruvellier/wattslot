// Lecture d'un nombre tapé dans un champ (common/NumberInput).

// Nombre écrit avec une virgule ou un point décimal, espaces tolérées ; null si le texte n'en
// forme pas un (vide, « - », « , »…).
export function parseNumber(text: string): number | null {
  const cleaned = text.replace(/\s/g, "").replace(",", ".");
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(cleaned)) return null;
  return Number(cleaned);
}
