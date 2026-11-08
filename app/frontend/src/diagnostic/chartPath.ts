// Tracé lissé des courbes de ressources : interpolation cubique monotone (Fritsch-Carlson, comme
// la « monotoneX » de d3). La courbe passe par chaque relevé sans jamais dépasser ses voisins : un
// creux reste un creux, un plat reste un plat, aucun pic inventé entre deux minutes.

type Point = [number, number];

const round = (value: number) => value.toFixed(1);

/** Pente de la tangente à chaque point : nulle sur un extremum local, sinon moyenne harmonique
 * pondérée des pentes voisines, ce qui garde la courbe monotone entre deux relevés. */
function tangents(points: Point[]): number[] {
  const n = points.length;
  const slopes = points.slice(1).map(([x, y], i) => (y - points[i][1]) / (x - points[i][0] || 1));
  return points.map((_, i) => {
    if (i === 0) return slopes[0];
    if (i === n - 1) return slopes[n - 2];
    const before = slopes[i - 1];
    const after = slopes[i];
    if (before * after <= 0) return 0;
    const dxBefore = points[i][0] - points[i - 1][0];
    const dxAfter = points[i + 1][0] - points[i][0];
    return (3 * (dxBefore + dxAfter)) / ((2 * dxAfter + dxBefore) / before + (dxAfter + 2 * dxBefore) / after);
  });
}

/** Chemin SVG (« M… C… ») passant par ``points``, triés par x. */
export function smoothPath(points: Point[]): string {
  if (points.length === 0) return "";
  const [first, ...rest] = points;
  let path = `M${round(first[0])},${round(first[1])}`;
  if (rest.length === 0) return path;
  const slope = tangents(points);
  rest.forEach(([x, y], index) => {
    const [x0, y0] = points[index];
    const third = (x - x0) / 3;
    path +=
      `C${round(x0 + third)},${round(y0 + slope[index] * third)} ` +
      `${round(x - third)},${round(y - slope[index + 1] * third)} ${round(x)},${round(y)}`;
  });
  return path;
}
