// Ressources de l'application (État de l'application) : processeur, mémoire et disque, lus par
// /api/diagnostic/resources toutes les 30 secondes. Première étape : des valeurs, sans alerte ;
// les seuils viendront de mesures réelles.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { SettingList } from "../ui/SettingRow";
import { formatNumber, formatPercent } from "./format";
import type { Resources } from "./types";

const REFRESH_MS = 30_000;
// En deçà, les pics ne couvrent pas encore une journée : « depuis le démarrage ».
const DAY_S = 23.5 * 3600;

type LoadState = { status: "loading" } | { status: "ready"; resources: Resources } | { status: "error" };

export default function ResourcesSection() {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Resources>("api/diagnostic/resources", controller.signal)
      .then((resources) => setLoad({ status: "ready", resources }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    const timer = window.setTimeout(() => setTick((count) => count + 1), REFRESH_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [tick]);

  const bytes = (value: number | null) => {
    if (value === null) return t("diagnostic.resources.unknown");
    return value >= 1e9
      ? t("diagnostic.gigabytes", { value: formatNumber(language, value / 1e9, 1) })
      : t("diagnostic.megabytes", { value: formatNumber(language, value / 1e6, 0) });
  };
  const help = (...parts: (string | null)[]) => parts.filter(Boolean).join(" · ");

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
          label={t("diagnostic.resources.memory")}
          value={bytes(r.memory_bytes)}
          description={help(
            r.memory_peak_bytes === null ? null : peak(bytes(r.memory_peak_bytes)),
            r.memory_limit_bytes === null
              ? null
              : t("diagnostic.resources.memory_limit", { value: bytes(r.memory_limit_bytes) }),
          )}
        />
        <Row
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

function Row({ label, value, description }: { label: string; value: string; description: string }) {
  return (
    <div className="ui-setting-row">
      <span>
        <span className="ui-row-label">{label}</span>
        {description && <span className="ui-row-help">{description}</span>}
      </span>
      <span className="settings-value">{value}</span>
    </div>
  );
}
