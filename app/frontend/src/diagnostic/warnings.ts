// Entités muettes, marquées dans le détail technique du diagnostic. Ce qui ne va pas est calculé
// par l'application depuis le lot 4.8 (/api/diagnostic/problems). Les durées sont mesurées par
// rapport à `generated_at` (heure du serveur), pas à l'horloge du navigateur.

import type { Diagnostic } from "./types";

export const SILENT_ENTITY_MS = 24 * 3_600_000; // aucun relevé depuis un jour

function age(diagnostic: Diagnostic, time: string | null): number {
  return time ? Date.parse(diagnostic.generated_at) - Date.parse(time) : Number.POSITIVE_INFINITY;
}

/** Entités suivies sans relevé aujourd'hui ni depuis un jour : capteur muet ou absent de HA. */
export function silentEntities(diagnostic: Diagnostic): string[] {
  return (diagnostic.ingestion?.entities ?? [])
    .filter(
      (entity) =>
        (diagnostic.today[entity.entity_id] ?? 0) === 0 &&
        age(diagnostic, entity.last_time) > SILENT_ENTITY_MS,
    )
    .map((entity) => entity.entity_id);
}
