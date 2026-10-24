import { useEffect, useState, type ReactNode } from "react";

import { getJson } from "../api";
import { retryConnection } from "../connection/service";
import { useI18n } from "../i18n/I18nProvider";
import { refreshStatus } from "../nav/status";
import ForecastComparison from "./ForecastComparison";
import ProblemsSection from "./ProblemsSection";
import ReportSection from "./ReportSection";
import { formatAge, formatDate, formatNumber, unitOf } from "./format";
import type { Diagnostic } from "./types";
import { silentEntities } from "./warnings";

const REFRESH_MS = 30_000;

type LoadState = { status: "loading" } | { status: "ready"; diagnostic: Diagnostic } | { status: "error" };

// Diagnostic pour tous (lot 4.8) : ce qui ne va pas et le rapport d'abord, le détail technique
// replié en dessous (avec l'état de l'application, passé par la page).
export default function DiagnosticScreen({ onNavigate, children }: {
  onNavigate: (target: string) => void;
  children?: ReactNode;
}) {
  const { t } = useI18n();
  const [version, setVersion] = useState(0);
  const [checking, setChecking] = useState(false);

  // « Vérifier à nouveau » reconnecte Home Assistant s'il était en erreur (le bouton fait
  // alors vraiment quelque chose), puis relit les problèmes.
  const checkAgain = async () => {
    setChecking(true);
    await retryConnection();
    setChecking(false);
    setVersion((count) => count + 1);
    refreshStatus();
  };

  return (
    <section>
      <h2 className="visually-hidden">{t("diagnostic.title")}</h2>
      <ProblemsSection version={version} onNavigate={onNavigate} />
      <button type="button" disabled={checking} onClick={() => void checkAgain()}>
        {t(checking ? "problems.checking" : "problems.refresh")}
      </button>
      <ReportSection />
      <details>
        <summary>{t("diagnostic.technical")}</summary>
        {children}
        <TechnicalDetail />
      </details>
    </section>
  );
}

function TechnicalDetail() {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });

  const [tick, setTick] = useState(0); // relecture : minuterie ou bouton

  useEffect(() => {
    const controller = new AbortController();
    getJson<Diagnostic>("api/diagnostic", controller.signal)
      .then((diagnostic) => setLoad({ status: "ready", diagnostic }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    const timer = window.setTimeout(() => setTick((count) => count + 1), REFRESH_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [tick]);

  if (load.status === "loading") return <p>{t("diagnostic.loading")}</p>;
  if (load.status === "error") return <p role="alert">{t("diagnostic.error")}</p>;

  const { diagnostic } = load;
  const { ingestion, aggregation, maintenance, planning, issues } = diagnostic;
  const silent = new Set(silentEntities(diagnostic));
  const bytes = (value: number) => t("diagnostic.megabytes", { value: formatNumber(language, value / 1e6, 0) });
  // Écrit depuis le démarrage, et ramené à une journée : l'usure du disque (SSD, eMMC).
  const writtenSummary = (written: number, startedAt: string) => {
    const days = (Date.parse(diagnostic.generated_at) - Date.parse(startedAt)) / 86_400_000;
    return t("diagnostic.disk_written_summary", {
      total: bytes(written),
      per_day: days > 0 ? formatNumber(language, written / 1e9 / days, 1) : "—",
      since: formatDate(language, startedAt),
    });
  };

  return (
    <>
      <p>
        {t("diagnostic.generated_at", { time: formatDate(language, diagnostic.generated_at) })}{" "}
        <button type="button" onClick={() => setTick((count) => count + 1)}>
          {t("diagnostic.refresh")}
        </button>
      </p>

      {ingestion && (
        <>
          <h3>{t("diagnostic.ingestion")}</h3>
          <p>
            {t("diagnostic.ingestion_summary", {
              entities: ingestion.entities.length,
              received: formatNumber(language, ingestion.received, 0),
              written: formatNumber(language, ingestion.written, 0),
              pending: formatNumber(language, ingestion.pending, 0),
              age: formatAge(language, ingestion.last_batch_at, diagnostic.generated_at),
            })}
          </p>
          <table>
            <thead>
              <tr>
                <th>{t("diagnostic.entity")}</th>
                <th>{t("diagnostic.role")}</th>
                <th>{t("diagnostic.last_value")}</th>
                <th>{t("diagnostic.age")}</th>
                <th>{t("diagnostic.today")}</th>
              </tr>
            </thead>
            <tbody>
              {ingestion.entities.map((entity) => (
                <tr key={entity.entity_id} className={silent.has(entity.entity_id) ? "silent" : undefined}>
                  <td>{entity.entity_id}</td>
                  <td>{t(`role.${entity.role}`)}</td>
                  <td>
                    {entity.last_value === null
                      ? "—"
                      : `${formatNumber(language, entity.last_value)} ${unitOf(entity.role)}`}
                  </td>
                  <td>{formatAge(language, entity.last_time, diagnostic.generated_at)}</td>
                  <td>{formatNumber(language, diagnostic.today[entity.entity_id] ?? 0, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {aggregation && (
        <>
          <h3>{t("diagnostic.aggregation")}</h3>
          <dl>
            {Object.entries(aggregation.complete_until).map(([period, until]) => (
              <div key={period}>
                <dt>{t(`diagnostic.period.${period}`)}</dt>
                <dd>{t("diagnostic.complete_until", { time: formatDate(language, until) })}</dd>
                {aggregation.history.since[period] && (
                  <dd>
                    {t("diagnostic.history_since", { time: formatDate(language, aggregation.history.since[period]) })}
                  </dd>
                )}
              </div>
            ))}
          </dl>
          <p>
            {t("diagnostic.history_imported", {
              count: aggregation.history.imported,
              written: formatNumber(language, aggregation.written, 0),
            })}
          </p>
        </>
      )}

      {maintenance && (
        <>
          <h3>{t("diagnostic.storage")}</h3>
          <dl>
            <dt>{t("diagnostic.disk_raw")}</dt>
            <dd>{bytes(maintenance.disk.raw_bytes)}</dd>
            <dt>{t("diagnostic.disk_graph")}</dt>
            <dd>{bytes(maintenance.disk.graph_bytes)}</dd>
            <dt>{t("diagnostic.disk_database")}</dt>
            <dd>{bytes(maintenance.disk.database_bytes)}</dd>
            {diagnostic.memory_bytes !== null && (
              <>
                <dt>{t("diagnostic.memory")}</dt>
                <dd>{bytes(diagnostic.memory_bytes)}</dd>
              </>
            )}
            {diagnostic.written_bytes !== null && diagnostic.started_at !== null && (
              <>
                <dt>{t("diagnostic.disk_written")}</dt>
                <dd>{writtenSummary(diagnostic.written_bytes, diagnostic.started_at)}</dd>
              </>
            )}
            <dt>{t("diagnostic.next_maintenance")}</dt>
            <dd>{formatDate(language, maintenance.next_run_at)}</dd>
            <dt>{t("diagnostic.last_maintenance")}</dt>
            <dd>
              {maintenance.last_run
                ? t("diagnostic.last_maintenance_summary", {
                    time: formatDate(language, maintenance.last_run.started_at),
                    days: maintenance.last_run.removed_days.length,
                    duration: formatNumber(language, maintenance.last_run.duration_s, 1),
                  })
                : "—"}
            </dd>
          </dl>
        </>
      )}

      {planning && (
        <>
          <h3>{t("diagnostic.planning")}</h3>
          <dl>
            <dt>{t("diagnostic.next_plan")}</dt>
            <dd>{planning.enabled ? formatDate(language, planning.next_run_at) : t("diagnostic.plan_disabled")}</dd>
            <dt>{t("diagnostic.last_plan")}</dt>
            <dd>
              {planning.last_report && planning.last_success_at
                ? t("diagnostic.last_plan_summary", {
                    time: formatDate(language, planning.last_success_at),
                    today: formatNumber(language, planning.last_report.seconds_today, 1),
                    total: formatNumber(
                      language,
                      planning.last_report.seconds_today +
                        (planning.last_report.seconds_tomorrow ?? 0) +
                        (planning.last_report.seconds_horizon ?? 0),
                      1,
                    ),
                  })
                : "—"}
            </dd>
          </dl>
        </>
      )}

      {issues && issues.length > 0 && (
        <>
          <h3>{t("diagnostic.configuration")}</h3>
          <ul>
            {issues.map((item, index) => (
              <li key={`${item.device}-${item.issue.code}-${index}`} className="issue">
                {t("diagnostic.issue_of", {
                  device: item.device,
                  issue: t(`issue.${item.issue.code}`, item.issue.params),
                })}
              </li>
            ))}
          </ul>
        </>
      )}

      <ForecastComparison />
    </>
  );
}
