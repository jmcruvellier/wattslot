// Éléments d'affichage du serveur MCP, partagés par la page Assistant et la sous-page
// « Assistant vocal » des Réglages : résultat de la vérification, bouton « Copier ».

import { useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import type { Check } from "./mcp";

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
