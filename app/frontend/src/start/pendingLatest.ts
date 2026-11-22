// Date et heure limite de la demande en attente de chaque appareil, pour l'aide du formulaire
// de demande (RequestForm). À part : un fichier de composant n'exporte que des composants.

/** Date de la demande en attente (pas encore lancée) de chaque appareil : celle que
 * « Changer la date » modifie, la plus récente. La liste du serveur donne les plus récentes
 * d'abord. */
export function pendingLatest(
  requests: { device: string; status: string; launched_on: string | null; latest: string | null }[],
): Record<string, string | null> {
  const found: Record<string, string | null> = {};
  for (const request of requests) {
    if (request.status === "open" && !request.launched_on && !(request.device in found)) {
      found[request.device] = request.latest;
    }
  }
  return found;
}

/** Heure limite (« terminé avant ») de la même demande en attente de chaque appareil ; null :
 * aucune. */
export function pendingFinish(
  requests: { device: string; status: string; launched_on: string | null; finish_hour?: number | null }[],
): Record<string, number | null> {
  const found: Record<string, number | null> = {};
  for (const request of requests) {
    if (request.status === "open" && !request.launched_on && !(request.device in found)) {
      found[request.device] = request.finish_hour ?? null;
    }
  }
  return found;
}
