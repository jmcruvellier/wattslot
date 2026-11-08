// Ressources de l'application (État de l'application) : processeur, mémoire et disque, lus par
// /api/diagnostic/resources toutes les 30 secondes. Les alertes (disque, mémoire, calcul lent)
// sont des problèmes du diagnostic, en tête de page. Chaque ligne se déplie sur sa courbe des
// dernières 24 h (/api/diagnostic/resources/history), lue seulement quand une ligne est ouverte.

import { useEffect, useState, type ReactNode } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import Icon from "../ui/Icon";
import { SettingList } from "../ui/SettingRow";
import { formatNumber, formatPercent } from "./format";
import ResourceChart, { type ChartPoint } from "./ResourceChart";
import type { ResourcePoint, Resources } from "./types";

type Kind = "cpu" | "memory" | "disk";

const REFRESH_MS = 30_000;
// En deçà, les pics ne couvrent pas encore une journée : « depuis le démarrage ».
const DAY_S = 23.5 * 3600;

type LoadState = { status: "loading" } | { status: "ready"; resources: Resources } | { status: "error" };

export default function ResourcesSection() {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [tick, setTick] = useState(0);
  const [open, setOpen] = useState<Set<Kind>>(new Set());
  const [points, setPoints] = useState<ResourcePoint[] | null>(null);
  const charts = open.size > 0;

  useEffect(() => {
    const controller = new AbortController();
    getJson<Resources>("api/diagnostic/resources", controller.signal)
      .then((resources) => setLoad({ status: "ready", resources }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    if (charts) {
      getJson<ResourcePoint[]>("api/diagnostic/resources/history", controller.signal)
        .then(setPoints)
        .catch(() => undefined); // courbe absente : la ligne garde ses valeurs
    }
    const timer = window.setTimeout(() => setTick((count) => count + 1), REFRESH_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [tick, charts]);

  const toggle = (kind: Kind, isOpen: boolean) =>
    setOpen((current) => {
      const next = new Set(current);
      if (isOpen) next.add(kind);
      else next.delete(kind);
      return next;
    });
  const series = (pick: (point: ResourcePoint) => number | null): ChartPoint[] =>
    (points ?? []).map((point) => ({ time: Date.parse(point.time), value: pick(point) }));
  const chart = (label: string, pick: (point: ResourcePoint) => number | null,
    format: (value: number) => string, max?: number) =>
    points === null ? (
      <p className="ui-row-help resource-chart-empty">{t("diagnostic.loading")}</p>
    ) : (
      <ResourceChart points={series(pick)} format={format} label={t("diagnostic.resources.chart_label", { name: label })} max={max} />
    );

  const bytes = (value: number | null) => {
    if (value === null) return t("diagnostic.resources.unknown");
    return value >= 1e9
      ? t("diagnostic.gigabytes", { value: formatNumber(language, value / 1e9, 1) })
      : t("diagnostic.megabytes", { value: formatNumber(language, value / 1e6, 0) });
  };
  // « Pic depuis le démarrage : … · limite du conteneur : … » : majuscule au premier élément.
  const help = (...parts: (string | null)[]) => {
    const text = parts.filter(Boolean).join(" · ");
    return text.charAt(0).toLocaleUpperCase(language) + text.slice(1);
  };

  let rows;
  if (load.status === "loading") {
    rows = <p className="ui-setting-row">{t("diagnostic.loading")}</p>;
  } else if (load.status === "error") {
    rows = (
      <p role="alert" className="ui-setting-row">
        {t("diagnostic.resources.error")}
      </p>
    );
  } else {
    const r = load.resources;
    const peak = (value: string) =>
      t(r.measured_s >= DAY_S ? "diagnostic.resources.peak_day" : "diagnostic.resources.peak_start", { value });
    rows = (
      <>
        <Row
          kind="cpu"
          onToggle={toggle}
          chart={chart(t("diagnostic.resources.cpu"), (p) => p.cpu_percent, (v) => formatPercent(language, v))}
          label={t("diagnostic.resources.cpu")}
          value={r.cpu_percent === null ? t("diagnostic.resources.unknown") : formatPercent(language, r.cpu_percent)}
          description={help(
            t("diagnostic.resources.cpu_average"),
            r.cpu_peak_percent === null ? null : peak(formatPercent(language, r.cpu_peak_percent)),
            r.cpu_cores === null
              ? null
              : t("diagnostic.resources.cores", { count: formatNumber(language, r.cpu_cores, 1) }),
          )}
        />
        <Row
          kind="memory"
          onToggle={toggle}
          chart={chart(t("diagnostic.resources.memory"), (p) => p.memory_bytes, bytes)}
          label={t("diagnostic.resources.memory")}
          value={bytes(r.memory_bytes)}
          description={help(
            r.memory_peak_bytes === null ? null : peak(bytes(r.memory_peak_bytes)),
            r.memory_limit_bytes === null
              ? null
              : t(
                  r.memory_limit_source === "container"
                    ? "diagnostic.resources.memory_limit_container"
                    : "diagnostic.resources.memory_limit_machine",
                  { value: bytes(r.memory_limit_bytes) },
                ),
          )}
        />
        <Row
          kind="disk"
          onToggle={toggle}
          chart={chart(
            t("diagnostic.resources.disk_free_title"),
            (p) => p.disk_free_bytes,
            bytes,
            r.disk_total_bytes ?? undefined,
          )}
          label={t("diagnostic.resources.disk")}
          value={bytes(r.disk_used_bytes)}
          description={
            r.disk_free_bytes === null || r.disk_total_bytes === null
              ? t("diagnostic.resources.disk_used")
              : help(
                  t("diagnostic.resources.disk_used"),
                  t("diagnostic.resources.disk_free", {
                    free: bytes(r.disk_free_bytes),
                    total: bytes(r.disk_total_bytes),
                  }),
                )
          }
        />
      </>
    );
  }

  return (
    <section aria-labelledby="resources-title">
      <h3 id="resources-title" className="home-summary-heading">
        {t("diagnostic.resources.title")}
      </h3>
      <SettingList>{rows}</SettingList>
    </section>
  );
}

function Row({ kind, label, value, description, chart, onToggle }: {
  kind: Kind;
  label: string;
  value: string;
  description: string;
  chart: ReactNode;
  onToggle: (kind: Kind, open: boolean) => void;
}) {
  return (
    <details
      className="ui-setting-row settings-details resource-row"
      onToggle={(event) => onToggle(kind, event.currentTarget.open)}
    >
      <summary>
        <span>
          <span className="ui-row-label">{label}</span>
          {description && <span className="ui-row-help">{description}</span>}
        </span>
        <span className="resource-row-value">
          <span className="settings-value">{value}</span>
          <Icon name="chevron-right" size={18} />
        </span>
      </summary>
      {chart}
    </details>
  );
}
