// État de l'application pour la pastille (lot 6b.2) : le problème le plus grave du diagnostic
// (/api/diagnostic/problems, lot 4.8), relu toutes les 5 minutes. « À surveiller » ne change pas
// la pastille ; sans réponse du serveur, elle ne s'affiche pas.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import type { Problem } from "../diagnostic/ProblemsSection";

export type StatusLevel = "ok" | "degraded" | "blocking";

export const STATUS_REFRESH_MS = 5 * 60 * 1000;

export function statusLevel(problems: Problem[]): StatusLevel {
  if (problems.some((problem) => problem.severity === "blocking")) return "blocking";
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
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);
  return level;
}
