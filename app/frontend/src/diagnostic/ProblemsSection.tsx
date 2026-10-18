// « Ce qui ne va pas » (lot 4.8) : le premier niveau du diagnostic. Les problèmes sont calculés
// par l'application (/api/diagnostic/problems), les plus graves d'abord ; chacun dit le geste à
// faire et où : une page de l'application ou la documentation de Home Assistant.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";

export interface Problem {
  code: string;
  severity: "blocking" | "degraded" | "watch";
  params: Record<string, string>;
  target: string | null;
  doc: string | null;
}

type Load = { status: "loading" } | { status: "ready"; problems: Problem[] } | { status: "error" };

export default function ProblemsSection({ version, onNavigate }: {
  version: number;
  onNavigate: (target: string) => void;
}) {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getJson<Problem[]>("api/diagnostic/problems", controller.signal)
      .then((problems) => setLoad({ status: "ready", problems }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [version]);

  // Message d'un problème ; les anomalies de configuration et du tableau Énergie reprennent les
  // textes de leur écran.
  const message = (problem: Problem): string => {
    const { issue, ...params } = problem.params;
    if (problem.code === "configuration_issue") return t(`configuration.issue.${issue}`, params);
    if (problem.code === "energy_dashboard_issue") {
      return t("problems.code.energy_dashboard_issue", {
        device: params.device,
        issue: t(`issue.${issue}`, params),
      });
    }
    return t(`problems.code.${problem.code}`, {
      ...params,
      role: params.role ? t(`role.${params.role}`) : "",
      component: params.component ? t(`problems.component.${params.component}`) : "",
    });
  };

  return (
    <section aria-labelledby="problems-title">
      <h3 id="problems-title">{t("problems.title")}</h3>
      {load.status === "loading" && <p>{t("problems.loading")}</p>}
      {load.status === "error" && <p role="alert">{t("problems.error")}</p>}
      {load.status === "ready" && load.problems.length === 0 && <p role="status">{t("problems.none")}</p>}
      {load.status === "ready" && load.problems.length > 0 && (
        <ul>
          {load.problems.map((problem, index) => (
            <li key={`${problem.code}-${index}`} data-severity={problem.severity}>
              <strong>{t(`problems.severity.${problem.severity}`)}</strong> : {message(problem)}
              {t(`problems.action.${problem.code}`) !== `problems.action.${problem.code}` && (
                <>
                  <br />
                  {t(`problems.action.${problem.code}`)}
                </>
              )}{" "}
              {problem.target && (
                <button type="button" onClick={() => onNavigate(problem.target as string)}>
                  {t("problems.open")}
                </button>
              )}{" "}
              {problem.doc && (
                <a href={problem.doc} target="_blank" rel="noreferrer">
                  {t(problem.code === "internal_error" ? "problems.ticket" : "problems.doc")}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
