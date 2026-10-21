// Éléments d'affichage du serveur MCP, partagés par la page Assistant et la sous-page
// « Assistant vocal » des Réglages : résultat de la vérification, bouton « Copier ».

import { useState } from "react";

import { ApiError, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { mcpAddress, type Check, type Connection } from "./mcp";

/** Adresse interne du serveur MCP, à copier ou à corriger (et à oublier pour revenir à celle
 * trouvée par l'application). */
export function McpAddress({
  connection,
  onChange,
}: {
  connection: Connection | null;
  onChange: (connection: Connection) => void;
}) {
  const { t } = useI18n();
  const address = mcpAddress(connection);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<"invalid" | "failed" | null>(null);

  const save = async (url: string | null) => {
    setError(null);
    try {
      onChange(await putJson<Connection>("api/assistant/connection", { mcp_url: url }));
      setEditing(null);
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 422 ? "invalid" : "failed");
    }
  };

  if (editing !== null) {
    return (
      <form
        className="assistant-address-form"
        onSubmit={(event) => {
          event.preventDefault();
          void save(editing.trim());
        }}
      >
        <label>
          {t("assistant.address.label")}{" "}
          <input inputMode="url" value={editing} onChange={(event) => setEditing(event.target.value)} />
        </label>{" "}
        <button type="submit">{t("assistant.address.save")}</button>{" "}
        {connection?.saved && (
          <button type="button" onClick={() => void save(null)}>
            {t("assistant.address.reset")}
          </button>
        )}{" "}
        <button type="button" onClick={() => setEditing(null)}>
          {t("assistant.address.cancel")}
        </button>
        {error && <p role="alert">{t(`assistant.address.${error}`)}</p>}
      </form>
    );
  }
  return (
    <p>
      {address ? (
        <>
          <code className="assistant-address">{address}</code> <CopyButton text={address} label={t("assistant.copy_address")} />
        </>
      ) : (
        <span className="dim">{t("assistant.address.unknown")}</span>
      )}{" "}
      <button type="button" onClick={() => setEditing(address ?? "http://")}>
        {t("assistant.address.edit")}
      </button>
    </p>
  );
}

/** État, résultat et bouton « Vérifier ». */
export function CheckResult({ check, onVerify }: { check: Check; onVerify: () => void }) {
  const { t } = useI18n();
  return (
    <>
      {check.status === "ok" && <p role="status">{t("assistant.check.ok", { tools: check.tools })}</p>}
      {check.status === "failed" && <p role="alert">{t("assistant.check.failed", { detail: check.detail })}</p>}
      <p>
        <button type="button" disabled={check.status === "checking"} onClick={onVerify}>
          {t(check.status === "checking" ? "assistant.check.checking" : "assistant.check.run")}
        </button>
      </p>
    </>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => setCopied(true))
          .catch(() => setCopied(false));
      }}
    >
      {t(copied ? "assistant.copied" : "assistant.copy")}
    </button>
  );
}
