// Rapport anonymisé à joindre à un ticket (lot 4.8, point n° 7) : préparé par l'application
// (/api/diagnostic/report), montré en entier avant d'être téléchargé. Il ne contient ni nom
// d'équipement, ni identifiant d'entité, ni position.

import { useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";

type State = { status: "idle" | "loading" | "error" } | { status: "ready"; text: string };

export default function ReportSection() {
  const { t } = useI18n();
  const [state, setState] = useState<State>({ status: "idle" });

  const prepare = async () => {
    setState({ status: "loading" });
    try {
      const report = await getJson<unknown>("api/diagnostic/report");
      setState({ status: "ready", text: JSON.stringify(report, null, 2) });
    } catch {
      setState({ status: "error" });
    }
  };

  const download = (text: string) => {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `wattslot-rapport-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section aria-labelledby="report-title">
      <h3 id="report-title">{t("report.title")}</h3>
      <p>{t("report.intro")}</p>
      <button type="button" disabled={state.status === "loading"} onClick={() => void prepare()}>
        {t("report.prepare")}
      </button>
      {state.status === "error" && <p role="alert">{t("report.error")}</p>}
      {state.status === "ready" && (
        <>
          <p>{t("report.preview")}</p>
          <pre aria-label={t("report.preview_label")} style={{ maxHeight: "20em", overflow: "auto" }}>
            {state.text}
          </pre>
          <button type="button" onClick={() => download(state.text)}>
            {t("report.download")}
          </button>
        </>
      )}
    </section>
  );
}
