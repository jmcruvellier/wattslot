// « Ce qui ne va pas » (lot 4.8) : le premier niveau du diagnostic. Les problèmes sont calculés
// par l'application (/api/diagnostic/problems), les plus graves d'abord ; chacun dit le geste à
// faire et où : une page de l'application ou la documentation de Home Assistant. En tête, une
// carte résume l'état (pastille, nombre par gravité, « Vérifier à nouveau ») ; la liste ne montre
// que les premiers problèmes, les autres se déplient : une longue liste ne cache pas le reste.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { connectionErrorParams } from "../connection/service";
import { useI18n } from "../i18n/I18nProvider";
import { statusLevel } from "../nav/status";
import { longDate } from "../plan/format";
import { useShowMore, VISIBLE_ITEMS } from "../ui/ShowMore";
import { formatDate, formatNumber } from "./format";

export interface Problem {
  code: string;
  severity: "blocking" | "degraded" | "watch";
  params: Record<string, string>;
  target: string | null;
  doc: string | null;
  setup?: boolean; // étape de la mise en route, avant le premier plan
}

type Load = { status: "loading" } | { status: "ready"; problems: Problem[] } | { status: "error" };

const SEVERITIES: Problem["severity"][] = ["blocking", "degraded", "watch"];
const RESOURCE_CODES = new Set(["disk_low", "backup_space", "memory_high", "memory_heavy"]);

export default function ProblemsSection({ version, onNavigate, checking, onCheck }: {
  version: number;
  onNavigate: (target: string) => void;
  checking: boolean;
  onCheck: () => void;
}) {
  const { t, language } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    // Après « Vérifier à nouveau » (version > 0), le serveur relit d'abord les états de HA.
    getJson<Problem[]>(
      version > 0 ? "api/diagnostic/problems?refresh=true" : "api/diagnostic/problems",
      controller.signal,
    )
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
    if (problem.code === "statistic_stale") {
      // Statistique externe qui ne publie plus : date de la dernière heure reçue.
      return t("problems.code.statistic_stale", {
        ...params,
        since: formatDate(language, params.since ?? null),
      });
    }
    if (RESOURCE_CODES.has(problem.code)) {
      // Ressources : nombres bruts du serveur (Go, Mo, %), écrits dans la langue de l'interface.
      const number = (value: string | undefined, digits: number) =>
        value ? formatNumber(language, Number(value), digits) : "";
      return t(`problems.code.${problem.code}`, {
        ...params,
        free: number(params.free, 1),
        needed: number(params.needed, 1),
        used: number(params.used, 0),
      });
    }
    return t(`problems.code.${problem.code}`, {
      ...connectionErrorParams(t, params),
      role: params.role ? t(`role.${params.role}`) : "",
      component: params.component ? t(`problems.component.${params.component}`) : "",
    });
  };

  const problems = load.status === "ready" ? load.problems : [];
  const level = load.status === "error" ? "blocking" : load.status === "ready" ? statusLevel(problems) : "setup";
  const title =
    load.status === "loading"
      ? t("problems.loading")
      : load.status === "error"
        ? t("problems.error")
        : problems.length === 0
          ? t("problems.none")
          : t("problems.count", { count: problems.length });
  // « Bloque le plan : 1 · À surveiller : 2 »
  const counts = SEVERITIES.map((severity) => [severity, problems.filter((p) => p.severity === severity).length] as const)
    .filter(([, count]) => count > 0)
    .map(([severity, count]) => t("problems.severity_count", { severity: t(`problems.severity.${severity}`), count }))
    .join(" · ");
  const { shown, toggle } = useShowMore(problems, VISIBLE_ITEMS, "li");

  return (
    <section aria-label={t("problems.title")}>
      <div className="ui-card settings-state">
        <span className="status-dot" data-level={level} aria-hidden="true" />
        <span className="settings-state-text">
          <span className="ui-row-label" role={load.status === "error" ? "alert" : "status"}>
            {title}
          </span>
          {counts && <span className="ui-row-help">{counts}</span>}
        </span>
        <button type="button" className="ui-button ui-button-quiet" disabled={checking} onClick={onCheck}>
          {t(checking ? "problems.checking" : "problems.refresh")}
        </button>
      </div>
      {problems.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("problems.title")}</h3>
          <ul className="ui-setting-list problem-list">
            {shown.map((problem, index) => {
              const action = t(`problems.action.${problem.code}`);
              return (
                <li key={`${problem.code}-${index}`} className="ui-setting-row problem" data-severity={problem.severity}>
                  <span>
                    <span className="problem-severity">{t(`problems.severity.${problem.severity}`)}</span>
                    <span className="problem-message">{message(problem)}</span>
                    {action !== `problems.action.${problem.code}` && <span className="ui-row-help">{action}</span>}
                  </span>
                  {(problem.target || problem.doc) && (
                    <span className="settings-actions">
                      {problem.target && (
                        <button type="button" onClick={() => onNavigate(problem.target as string)}>
                          {t("problems.open")}
                        </button>
                      )}
                      {problem.doc && (
                        <a className="ui-button ui-button-quiet" href={problem.doc} target="_blank" rel="noreferrer">
                          {t(problem.code === "internal_error" ? "problems.ticket" : "problems.doc")}
                        </a>
                      )}
                    </span>
                  )}
                </li>
              );
            })}
            {toggle}
          </ul>
        </>
      )}
    </section>
  );
}
