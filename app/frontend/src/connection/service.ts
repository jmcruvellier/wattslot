// Connexion à Home Assistant, côté serveur : état et codes d'erreur stables (traduits par le
// catalogue, le détail technique reste dans le rapport de signalement), demande de
// reconnexion immédiate. Les codes viennent de ``wattslot.home_assistant`` (_code_of).

import { postJson } from "../api";

export interface ConnectionInfo {
  mode: "addon" | "standalone";
  source: "supervisor" | "env" | "saved" | null;
  url: string | null;
  method: "oauth" | "token" | null;
  state: "not_configured" | "connecting" | "connected" | "error";
  error: string | null;
  error_code: string | null;
}

type Translate = (key: string, params?: Record<string, string | number>) => string;

/** Phrase pour l'utilisateur à partir du code d'erreur du serveur. */
export function connectionError(t: Translate, code: string | null | undefined): string {
  return t(`connection_error.${code ?? "unknown"}`);
}

/** Paramètres d'un message de l'application : le code d'erreur devient une phrase traduite. */
export function connectionErrorParams(
  t: Translate,
  params: Record<string, string>,
): Record<string, string> {
  const { error_code, ...rest } = params;
  return error_code === undefined ? rest : { ...rest, error: connectionError(t, error_code) };
}

/** Reconnecte Home Assistant tout de suite ; ``null`` si le serveur n'a pas répondu. Sans
 *  effet si tout va bien déjà : la reconnexion automatique suit son cours. */
export async function retryConnection(): Promise<ConnectionInfo | null> {
  try {
    return await postJson<ConnectionInfo>("api/connection/retry", {});
  } catch {
    return null;
  }
}
