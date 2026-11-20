// Tracé des liaisons de la frise entre les cycles de deux équipements qui se suivent (le
// sèche-linge après le lave-linge). Le serveur donne chaque liaison : la ligne du cycle suivi,
// celle du cycle qui le suit, l'heure de fin du premier et l'heure de début du second. Ici, on
// décide seulement comment la tracer sans rien recouvrir.
//
// Tracé ordinaire, à deux angles : le trait sort à l'horizontale du milieu du bord droit du bloc
// suivi et file dans l'espace vide de sa ligne, descend une seule fois, puis rejoint à
// l'horizontale, dans l'espace vide de la ligne du dessous, le milieu du bord gauche du bloc qui
// suit. La descente (`via`) est au milieu de l'espace libre commun aux deux lignes — après le
// cycle suivi et avant le bloc suivant de sa ligne, après le bloc précédent de la ligne du
// dessous et avant le cycle qui suit —, pas collée à un bloc. Deux cycles qui se touchent : un
// simple trait vertical. Deux liaisons de la même ligne ne se croisent pas : la descente de la
// première est avant le cycle suivi de la seconde.
//
// Sans espace libre commun (un autre bloc commence sur la ligne du dessus avant que celle du
// dessous soit libre), tracé de repli par la marge entre les deux pistes, à quatre angles : une
// courte sortie horizontale, la descente jusqu'à un « couloir » horizontal dans la marge, une
// redescente un peu avant le cycle qui suit et une courte entrée horizontale. Deux liaisons de
// repli dont les parcours se recouvrent prennent deux couloirs, la plus tardive au-dessus. La
// sortie et l'entrée raccourcissent quand un autre bloc de la ligne est tout près.

import type { Timeline } from "./types";

export interface LinkShape {
  from: number; // heure de fin du cycle suivi
  to: number; // heure de début du cycle qui le suit
  started: boolean; // trait plein ; sinon pointillé
  via: number | null; // heure de la descente du tracé à deux angles ; null : tracé de repli
  lane: number; // couloir horizontal : 0, le plus près de la piste d'arrivée
  lanes: number; // nombre de couloirs pris au-dessus de cette piste
  skip: number; // lignes entre celle du cycle suivi et celle-ci (0 : juste au-dessus)
  roomAfter: number; // heures libres après le cycle suivi, sur sa ligne, avant un autre bloc
  roomBefore: number; // heures libres avant le cycle qui suit, sur sa ligne, après un autre bloc
}

// Marge, en heures, pour dire que deux parcours se recouvrent.
const MARGIN_HOURS = 0.1;
// Précision des heures : un bloc qui commence à la fin d'un autre le touche.
const SAME_HOURS = 0.01;

const clamp = (hour: number) => Math.min(Math.max(hour, 0), 24);

/** Liaisons à tracer, par ligne d'arrivée (`device`), dans l'ordre de la journée. */
export function linkShapes(timeline: Timeline): Map<string, LinkShape[]> {
  const found = new Map<string, LinkShape[]>();
  const index = new Map(timeline.rows.map((row, position) => [row.device, position]));
  const links = [...(timeline.links ?? [])].sort((a, b) => a.to_hour - b.to_hour || a.from_hour - b.from_hour);
  for (const link of links) {
    const source = index.get(link.source);
    const target = index.get(link.target);
    if (source === undefined || target === undefined || source >= target) continue;
    const row = timeline.rows[target];
    const from = clamp(link.from_hour);
    const to = clamp(link.to_hour);
    const shapes = found.get(link.target) ?? [];
    const above = [...timeline.rows[source].planned, ...timeline.rows[source].actual];
    const below = [...row.planned, ...row.actual];
    // Place libre après le cycle suivi sur sa ligne, et avant le cycle qui suit sur la sienne.
    const roomAfter = Math.min(
      ...above.filter((bar) => bar.start_hour >= from - SAME_HOURS).map((bar) => Math.max(bar.start_hour - from, 0)),
      24 - from,
    );
    const roomBefore = Math.min(
      ...below.filter((bar) => bar.end_hour <= to + SAME_HOURS).map((bar) => Math.max(to - bar.end_hour, 0)),
      to,
    );
    // Descente possible entre `lowest` et `highest` : ni avant le cycle suivi ou la fin du bloc
    // précédent de la ligne du dessous, ni après le cycle qui suit, le bloc suivant de la ligne
    // du dessus ou le début d'un bloc prévu qui couvre l'arrivée (son crochet).
    const lowest = Math.max(from, to - roomBefore);
    const highest = Math.min(
      to,
      from + roomAfter,
      ...below
        .filter((bar) => bar.start_hour < to - SAME_HOURS && bar.end_hour > to + SAME_HOURS)
        .map((bar) => bar.start_hour),
    );
    const via = lowest <= highest ? (lowest + highest) / 2 : null;
    const previous = via === null ? shapes.filter((shape) => shape.via === null).pop() : undefined;
    const overlaps =
      previous !== undefined &&
      Math.min(from, to) <= Math.max(previous.from, previous.to) + MARGIN_HOURS &&
      Math.min(previous.from, previous.to) <= Math.max(from, to) + MARGIN_HOURS;
    shapes.push({
      from,
      to,
      started: link.started,
      via,
      lane: overlaps && previous ? previous.lane + 1 : 0,
      lanes: 1,
      skip: target - source - 1,
      roomAfter,
      roomBefore,
    });
    found.set(link.target, shapes);
  }
  for (const shapes of found.values()) {
    const lanes = Math.max(...shapes.map((shape) => shape.lane)) + 1;
    for (const shape of shapes) shape.lanes = lanes;
  }
  return found;
}

// Les couloirs tiennent dans la marge libre entre deux pistes : 0,4 rem sous les blocs de la
// piste du dessus (sur un téléphone : sous le nom de la ligne), 0,4 rem au-dessus des crochets
// de celle du dessous.
const LOWEST_REM = 0.22;
const SPREAD_REM = 0.38;

/** Hauteur du couloir du tracé de repli, en rem depuis le haut de la piste d'arrivée (négatif : au-dessus). */
export function laneOffset(shape: LinkShape): number {
  if (shape.lanes <= 1) return 0.2;
  return LOWEST_REM - (shape.lane * SPREAD_REM) / (shape.lanes - 1);
}

// Sortie et entrée horizontales : 8 pixels, moins quand un autre bloc est tout près (la moitié
// de la place libre), jamais moins de 2.
const STUB_PX = 8;
const STUB_MIN_PX = 2;

/** Longueur, en pixels, de la sortie et de l'entrée horizontales ; `trackWidth` : largeur de la
 * piste (0 si elle n'est pas connue : la longueur ordinaire). */
export function stubPx(shape: LinkShape, trackWidth: number): number {
  if (trackWidth <= 0) return STUB_PX;
  const room = (Math.min(shape.roomAfter, shape.roomBefore) / 24) * trackWidth;
  return Math.max(STUB_MIN_PX, Math.min(STUB_PX, room / 2));
}

/** Le couloir revient-il vers la gauche (cycles trop proches pour une sortie et une entrée) ? */
export function turnsBack(shape: LinkShape, trackWidth: number): boolean {
  const half = (((shape.to - shape.from) / 24) * trackWidth) / 2;
  return trackWidth > 0 ? half < stubPx(shape, trackWidth) : shape.to <= shape.from;
}
