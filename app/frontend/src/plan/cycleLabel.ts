// Nom affiché d'un cycle hors de la frise (« La journée », tuile « Appareils », « Mes demandes »).
// Le serveur nomme un cycle par son identité : le nom de l'équipement pour le premier de la
// journée, ce nom et son rang ensuite (« Sèche-linge », « Sèche-linge #2 »). Dès qu'un
// équipement a plusieurs cycles, le premier se lisait sans numéro à côté du « #2 » : on ne savait
// pas lequel marquer « Fait » (constaté le 28/11/2026). Il s'affiche alors « #1 ». L'identité,
// elle, ne change pas : c'est elle que prennent les actions.

const RANK = / #\d+$/;

/** Identité → nom affiché, pour les cycles donnés (ceux d'une même journée). */
export function cycleLabels(cycles: Iterable<string>): Map<string, string> {
  const found = [...new Set(cycles)];
  const count = new Map<string, number>();
  for (const cycle of found) {
    const device = cycle.replace(RANK, "");
    count.set(device, (count.get(device) ?? 0) + 1);
  }
  return new Map(
    found.map((cycle) => [cycle, RANK.test(cycle) || (count.get(cycle) ?? 0) < 2 ? cycle : `${cycle} #1`]),
  );
}
