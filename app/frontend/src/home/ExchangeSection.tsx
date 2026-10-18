// Export et import de la maison (lot 3.8) : un fichier JSON versionné, modèle de la maison et
// configuration. L'import est vérifié avant d'être appliqué ; appliqué, il remplace les deux.

import { useState } from "react";

import { ApiError } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import type { ConfigurationIssue } from "./configuration";

interface ImportCheck {
  issues: ConfigurationIssue[];
  unknown_entities: string[];
  applied: boolean;
}

type State =
  | { status: "idle" | "checking" | "applying" | "applied" | "unreadable" | "failed" }
  | { status: "checked"; document: unknown; check: ImportCheck };

async function postImport(document: unknown, dryRun: boolean): Promise<ImportCheck> {
  const response = await fetch(`api/configuration/import${dryRun ? "?dry_run=true" : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(document),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as ImportCheck;
}

export default function ExchangeSection({ onImported }: { onImported: () => void }) {
  const { t } = useI18n();
  const [state, setState] = useState<State>({ status: "idle" });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setState({ status: "checking" });
    let document: unknown;
    try {
      document = JSON.parse(await file.text());
    } catch {
      setState({ status: "unreadable" });
      return;
    }
    try {
      setState({ status: "checked", document, check: await postImport(document, true) });
    } catch {
      setState({ status: "failed" });
    }
  };

  const onApply = async (document: unknown) => {
    setState({ status: "applying" });
    try {
      await postImport(document, false);
      setState({ status: "applied" });
      onImported();
    } catch {
      setState({ status: "failed" });
    }
  };

  return (
    <section aria-labelledby="exchange-title">
      <h2 className="visually-hidden" id="exchange-title">{t("exchange.title")}</h2>
      <p>{t("exchange.intro")}</p>
      <p>
        <a href="api/configuration/export" download>
          {t("exchange.export")}
        </a>{" "}
        <a href="api/configuration/export.ttl" download>
          {t("exchange.export_turtle")}
        </a>
      </p>
      <label>
        {t("exchange.import")}{" "}
        <input type="file" accept="application/json,.json" onChange={(event) => void onFile(event.target.files?.[0])} />
      </label>
      {state.status === "checked" && (
        <div>
          {state.check.issues.length > 0 ? (
            <ul role="alert">
              {state.check.issues.map((issue, index) => (
                <li key={`${issue.code}-${index}`} className="issue">
                  {t(`configuration.issue.${issue.code}`, { ...issue.params, device: issue.device ?? "" })}
                </li>
              ))}
            </ul>
          ) : (
            <>
              <p role="status">{t("exchange.valid")}</p>
              {state.check.unknown_entities.length > 0 && (
                <p>{t("exchange.unknown_entities", { entities: state.check.unknown_entities.join(", ") })}</p>
              )}
              <button type="button" onClick={() => void onApply(state.document)}>
                {t("exchange.apply")}
              </button>
            </>
          )}
        </div>
      )}
      {state.status === "applied" && <p role="status">{t("exchange.applied")}</p>}
      {state.status === "unreadable" && <p role="alert">{t("exchange.unreadable")}</p>}
      {state.status === "failed" && <p role="alert">{t("exchange.failed")}</p>}
    </section>
  );
}
