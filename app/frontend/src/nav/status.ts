// État de l'application pour la pastille (lot 6b.2) : le problème le plus grave du diagnostic
// (/api/diagnostic/problems, lot 4.8), relu toutes les 5 minutes, à chaque changement d'écran et
// après un calcul (`refreshStatus`). « À surveiller » ne change pas la pastille ; sans réponse du
// serveur, elle ne s'affiche pas. Avant le premier plan, les étapes de la mise en route ne
// bloquent rien : « Mise en route », sans rouge.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import type { Problem } from "../diagnostic/ProblemsSection";

export type StatusLevel = "ok" | "setup" | "degraded" | "blocking";

export const STATUS_REFRESH_MS = 5 * 60 * 1000;
const STATUS_EVENT = "wattslot:status";

/** Relit la pastille tout de suite (après un calcul, par exemple). */
export function refreshStatus() {
  window.dispatchEvent(new Event(STATUS_EVENT));
}

export function statusLevel(problems: Problem[]): StatusLevel {
  const blocking = problems.filter((problem) => problem.severity === "blocking");
  if (blocking.length > 0) return blocking.every((problem) => problem.setup) ? "setup" : "blocking";
  if (problems.some((problem) => problem.severity === "degraded")) return "degraded";
  return "ok";
}

export function useStatusLevel(): StatusLevel | null {
  const [level, setLevel] = useState<StatusLevel | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const read = () =>
      getJson<Problem[]>("api/diagnostic/problems", controller.signal)
        .then((problems) => setLevel(statusLevel(problems)))
        .catch(() => {
          if (!controller.signal.aborted) setLevel(null);
        });
    void read();
    const timer = window.setInterval(() => void read(), STATUS_REFRESH_MS);
    const now = () => void read();
    window.addEventListener("hashchange", now);
    window.addEventListener(STATUS_EVENT, now);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener("hashchange", now);
      window.removeEventListener(STATUS_EVENT, now);
    };
  }, []);
  return level;
}
