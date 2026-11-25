// Nom d'un cycle dans la légende de la frise. Dès qu'un équipement a plusieurs cycles dans la
// journée, chacun porte son numéro dans l'ordre de la journée (« Lave-linge #1 »,
// « Lave-linge #2 »), qu'il ait été prévu ou non : deux lessives lancées sans demande se
// lisaient toutes deux « Lave-linge » (constaté le 20/11/2026).
//
// Les cycles de la journée sont, dans l'ordre :
// - la suite d'un cycle commencé la veille, s'il y en a une : le premier de la journée ;
// - les activités mesurées qui sont des cycles : celles que le bilan du serveur a reconnues
//   comme le démarrage d'un cycle prévu, et celles d'au moins `CYCLE_FRACTION` de la plus grosse
//   activité de la journée (un réveil de veille de quelques minutes n'est pas un cycle) ;
// - les cycles prévus pas encore démarrés, dans l'ordre de leur départ.
// Un bloc prévu déjà démarré porte le numéro de son activité.

import type { Bar, DeviceStatus, TimelineRow } from "./types";

const CYCLE_FRACTION = 0.3; // comme le profil des cycles du serveur
const MIDNIGHT_HOURS = 0.25; // activité en cours à minuit : la suite du cycle de la veille

export function cycleNames(row: TimelineRow, statuses: DeviceStatus[]): Map<Bar, string> {
  const names = new Map<Bar, string>();
  if (row.kind !== "cycle") return names;
  const own = statuses.filter((status) => (status.appliance ?? status.device) === row.device);
  const startOf = (bar: Bar) =>
    own.find(
      (status) => status.actual_start_min !== null && Math.abs(status.actual_start_min - bar.start_hour * 60) < 1,
    );
  const biggest = Math.max(0, ...row.actual.map((bar) => bar.energy_kwh));
  const measured = row.actual
    .filter((bar) => startOf(bar) !== undefined || (bar.energy_kwh > 0 && bar.energy_kwh >= CYCLE_FRACTION * biggest))
    .sort((a, b) => a.start_hour - b.start_hour);
  // Activité de chaque cycle prévu déjà démarré (identité du cycle → son activité).
  const started = new Map<string, Bar>();
  for (const bar of measured) {
    const status = startOf(bar);
    if (status) started.set(status.device, bar);
  }
  const carried = row.planned.filter((bar) => bar.carried);
  // La suite de la veille est le premier cycle de la journée ; mesurée dès minuit, c'est la
  // première activité, sinon elle compte pour un cycle de plus.
  const carriedAlone = carried.length > 0 && !(measured[0] && measured[0].start_hour < MIDNIGHT_HOURS);
  const offset = carriedAlone ? 1 : 0;
  // Identité du cycle d'un bloc prévu ; sans elle (premier cycle), le nom de l'équipement.
  const identity = (bar: Bar) => bar.cycle ?? row.device;
  const pending = row.planned
    // Un bloc dit lancé par le serveur montre son créneau annoncé : pas un cycle de plus.
    .filter((bar) => !bar.carried && !bar.launched && !started.has(identity(bar)))
    .sort((a, b) => a.start_hour - b.start_hour);
  if (offset + measured.length + pending.length < 2) return names;
  const name = (rank: number) => `${row.device} #${rank}`;
  measured.forEach((bar, index) => names.set(bar, name(offset + index + 1)));
  carried.forEach((bar) => names.set(bar, name(1)));
  pending.forEach((bar, index) => names.set(bar, name(offset + measured.length + index + 1)));
  for (const bar of row.planned) {
    const activity = bar.carried ? undefined : started.get(identity(bar));
    const known = activity ? names.get(activity) : undefined;
    if (known) names.set(bar, known);
  }
  return names;
}
