// Adresses de la connexion à HA (lot 4.6), à part pour être partagées avec la page.

/** Adresse de l'application vue du navigateur : HA y renverra après la connexion. */
export function applicationAddress(location: Location = window.location): string {
  return `${location.origin}${location.pathname}`.replace(/\/$/, "");
}

/** Retour de HA (« ?connection=ok ») lu dans l'adresse de la page. */
export function returnedFromHomeAssistant(search: string = window.location.search): string | null {
  return new URLSearchParams(search).get("connection");
}
