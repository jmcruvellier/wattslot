// Disposition du graphe de la maison : fonction pure, indépendante du rendu. Deux vues :
// l'ontologie entière (anneaux concentriques, un secteur par type de la bibliothèque) et
// l'intérieur d'un élément double-cliqué (lui au centre, ses voisins autour). Dans les deux,
// chaque nœud réserve au moins sa largeur sur son anneau : deux objets ne peuvent pas se
// chevaucher, quitte à élargir les rayons quand le modèle ne tient pas dans le cercle.

import type { Graph, NodeKind } from "./graph";

// Largeur d'un nœud du dessin (12,5rem ≈ 200px) avec sa marge, et anneaux : un pas par niveau.
export const NODE_SPACING = 260;
export const LEVEL_RADIUS = 480; // rayon du premier anneau, puis un pas par niveau
export const RADIUS_STEP = 400;

// Profondeur de chaque nature d'objet, du centre du dessin vers l'extérieur.
const LEVELS: Record<NodeKind, number> = { library: 0, type: 1, device: 2, sensor: 3 };

export type Position = { x: number; y: number };

// Branche d'un type de la bibliothèque : ses types propres et équipements, puis leurs capteurs.
// Le sens des liens n'est pas uniforme (« est un » pointe vers le parent, « capteur » vers
// l'enfant) : dans un lien, l'enfant est toujours l'objet du niveau le plus profond.
type Branch = { id: string; kind: NodeKind; children: Branch[] };

function branchTree(graph: Graph): Branch[] {
  const levelOf = (id: string) => {
    const node = graph.nodes.find((n) => n.id === id);
    return node ? LEVELS[node.kind] : -1;
  };
  const childrenOf = (id: string) => {
    const level = levelOf(id);
    const children: string[] = [];
    for (const edge of graph.edges) {
      if (edge.target === id && levelOf(edge.source) > level) children.push(edge.source);
      if (edge.source === id && levelOf(edge.target) > level) children.push(edge.target);
    }
    return [...new Set(children)];
  };
  const build = (id: string): Branch => {
    const node = graph.nodes.find((n) => n.id === id);
    return { id, kind: node?.kind ?? "library", children: childrenOf(id).map(build) };
  };
  return graph.nodes.filter((node) => node.kind === "library").map((node) => build(node.id));
}

const radiusOf = (kind: NodeKind, scale: number) => (LEVEL_RADIUS + LEVELS[kind] * RADIUS_STEP) * scale;

// Angle nécessaire à une branche pour que ses nœuds ne se chevauchent pas : au moins la largeur
// réservée du nœud sur son anneau, ou la somme des besoins de ses enfants si elle est plus large.
function angleNeeded(branch: Branch, scale: number): number {
  const own = NODE_SPACING / radiusOf(branch.kind, scale);
  const children = branch.children.reduce((sum, child) => sum + angleNeeded(child, scale), 0);
  return Math.max(own, children);
}

// Place une branche dans son secteur : la racine au milieu du secteur, ses enfants côte à côte,
// chacun avec une part du secteur proportionnelle à son besoin.
function placeBranch(branch: Branch, angleStart: number, angleEnd: number, scale: number, positions: Map<string, Position>) {
  const radius = radiusOf(branch.kind, scale);
  const middle = (angleStart + angleEnd) / 2;
  positions.set(branch.id, { x: Math.round(Math.cos(middle) * radius), y: Math.round(Math.sin(middle) * radius) });
  if (branch.children.length === 0) return;
  const sector = angleEnd - angleStart;
  const needs = branch.children.map((child) => angleNeeded(child, scale));
  const total = needs.reduce((sum, need) => sum + need, 0);
  let cursor = angleStart;
  branch.children.forEach((child, index) => {
    const span = (sector * needs[index]) / total;
    placeBranch(child, cursor, cursor + span, scale, positions);
    cursor += span;
  });
}

// Vue globale : chaque type de la bibliothèque reçoit un secteur d'angle proportionnel à son
// besoin ; si l'ensemble ne tient pas dans le cercle, tous les rayons s'élargissent du même
// facteur, ce qui resserre les angles exactement de ce qu'il faut — les largeurs sont gardées.
export function layout(graph: Graph): Map<string, Position> {
  const positions = new Map<string, Position>();
  const branches = branchTree(graph);
  if (branches.length > 0) {
    let scale = 1;
    if (branches.reduce((sum, branch) => sum + angleNeeded(branch, scale), 0) > 2 * Math.PI) {
      const total = branches.reduce((sum, branch) => sum + angleNeeded(branch, scale), 0);
      scale = total / (2 * Math.PI); // les rayons s'élargissent, les besoins d'angle diminuent d'autant
    }
    const needs = branches.map((branch) => angleNeeded(branch, scale));
    const total = needs.reduce((sum, need) => sum + need, 0);
    const stretch = (2 * Math.PI) / total; // ≥ 1 : les secteurs remplissent le cercle
    let cursor = -Math.PI / 2;
    branches.forEach((branch, index) => {
      const span = needs[index] * stretch;
      placeBranch(branch, cursor, cursor + span, scale, positions);
      cursor += span;
    });
  }
  // Objets sans branche (hors arbre) : dernier recours, au centre.
  for (const node of graph.nodes) {
    if (!positions.has(node.id)) positions.set(node.id, { x: 0, y: 0 });
  }
  return positions;
}

// Vue d'un élément, après un double-clic : il passe au centre et ses voisins l'entourent — les
// liaisons directes seulement, pour entrer dans le détail de sa branche. Le rayon du cercle
// garantit là aussi la largeur réservée de chaque voisin.
export function layoutInside(graph: Graph, focus: string): { positions: Map<string, Position>; ids: string[] } {
  const positions = new Map<string, Position>([[focus, { x: 0, y: 0 }]]);
  const links = graph.edges.filter((edge) => edge.source === focus || edge.target === focus);
  const neighbors = [...new Set(links.flatMap((edge) => [edge.source, edge.target]))].filter((id) => id !== focus);
  const radius = Math.max(360, (neighbors.length * NODE_SPACING) / (2 * Math.PI));
  neighbors.forEach((id, index) => {
    const angle = (2 * Math.PI * index) / neighbors.length - Math.PI / 2;
    positions.set(id, { x: Math.round(Math.cos(angle) * radius), y: Math.round(Math.sin(angle) * radius) });
  });
  return { positions, ids: [focus, ...neighbors] };
}
