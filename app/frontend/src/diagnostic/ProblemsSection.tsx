// « Ce qui ne va pas » (lot 4.8) : le premier niveau du diagnostic. Les problèmes sont calculés
// par l'application (/api/diagnostic/problems), les plus graves d'abord ; chacun dit le geste à
// faire et où : une page de l'application ou la documentation de Home Assistant.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { connectionErrorParams } from "../connection/service";
import { useI18n } from "../i18n/I18nProvider";
import { longDate } from "../plan/format";
import { formatNumber } from "./format";

export interface Problem {
  code: string;
  severity: "blocking" | "degraded" | "watch";
  params: Record<string, string>;
  target: string | null;
  doc: string | null;
  setup?: boolean; // étape de la mise en route, avant le premier plan
}

type Load = { status: "loading" } | { status: "ready"; problems: Problem[] } | { status: "error" };

export default function ProblemsSection({ version, onNavigate }: {
  version: number;
  onNavigate: (target: string) => void;
}) {
  const { t, language } = useI18n();
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
    if (problem.code === "impossible_data" || problem.code === "impossible_data_unknown") {
      // Saut de compteur (lot 7.3) : dates, heures et énergies dans la langue de l'interface.
      const hour = (value: string) => t("problems.hour", { hour: value });
      return t(`problems.code.${problem.code}`, {
        ...params,
        day: longDate(params.day, language),
        hour: hour(params.hour),
        kwh: formatNumber(language, Number(params.kwh), 0),
        limit: formatNumber(language, Number(params.limit), 1),
        ...(problem.code === "impossible_data" && {
          when: longDate(params.when, language),
          when_hour: hour(params.when_hour),
          source_kwh: formatNumber(language, Number(params.source_kwh), 0),
          until: longDate(params.until, language),
        }),
      });
    }
    return t(`problems.code.${problem.code}`, {
      ...connectionErrorParams(t, params),
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
