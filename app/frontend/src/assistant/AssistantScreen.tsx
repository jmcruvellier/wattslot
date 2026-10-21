// Page « Assistant » (lot 6.3) : brancher l'Assist de Home Assistant sur le serveur MCP de
// l'application, avec le LLM qu'on a déjà. Adresse du serveur à copier (selon le mode), réglages
// de l'agent de conversation, prompt conseillé, vérification que le serveur répond. Lot 6b.6 :
// en cartes, l'état d'abord (vérifié à l'ouverture), le branchement replié une fois vérifié.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import ChatCard from "./ChatCard";
import { checkTitle, useConnection, useMcpCheck } from "./mcp";
import { CheckResult, CopyButton, McpAddress } from "./McpParts";

const CHAT_INPUT = "assistant-chat-input";
const EXAMPLES = ["why", "yesterday", "battery", "request"] as const;

/** Question d'exemple sans ses guillemets, pour la zone de saisie du chat. */
function unquoted(text: string): string {
  return text.replace(/^[«"“„‚‘]\s*/, "").replace(/\s*[»"”“‘’]$/, "");
}

interface AssistantPrompt {
  language: string;
  prompt: string;
}

export default function AssistantScreen() {
  const { language, t } = useI18n();
  const [connection, setConnection] = useConnection();
  const [prompt, setPrompt] = useState<string | null>(null);
  const [check, verify] = useMcpCheck();
  const [draft, setDraft] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getJson<AssistantPrompt>(`api/assistant/prompt?lang=${language}`, controller.signal)
      .then((found) => setPrompt(found.prompt))
      .catch(() => setPrompt(null));
    return () => controller.abort();
  }, [language]);

  // La discussion avec l'assistant, puis l'assistant vocal (lot 6b.6) : son état, des exemples
  // de questions (qui remplissent la zone de saisie du chat), et le branchement pas à pas, replié
  // une fois le serveur vérifié. « Mes demandes » est dans Planning, à côté du plan.
  return (
    <div className="assistant">
      <ChatCard inputId={CHAT_INPUT} draft={draft} onDraft={setDraft} />
      <section className="ui-card" aria-labelledby="assistant-title">
        <p className="ui-eyebrow">{t("assistant.title")}</p>
        <h2 id="assistant-title" className="ui-card-title">
          {t(checkTitle(check))}
        </h2>
        <p>{t("assistant.intro")}</p>
        <CheckResult check={check} onVerify={() => void verify()} />

        <h3>{t("assistant.examples.title")}</h3>
        <ul className="assistant-examples">
          {EXAMPLES.map((key) => (
            <li key={key}>
              <button
                type="button"
                onClick={() => {
                  setDraft(unquoted(t(`assistant.examples.${key}`)));
                  document.getElementById(CHAT_INPUT)?.focus();
                }}
              >
                {t(`assistant.examples.${key}`)}
              </button>
            </li>
          ))}
        </ul>

        <details className="plan-more" open={check.status !== "ok" || undefined}>
          <summary>{t("assistant.setup")}</summary>
          <h3>{t("assistant.step1.title")}</h3>
          <p>{t("assistant.step1.help")}</p>
          <McpAddress connection={connection} onChange={setConnection} />
          <p className="dim">{t(connection?.mode === "addon" ? "assistant.step1.addon" : "assistant.step1.standalone")}</p>

          <h3>{t("assistant.step2.title")}</h3>
          <ul>
            <li>{t("assistant.step2.agent")}</li>
            <li>{t("assistant.step2.model")}</li>
            <li>{t("assistant.step2.api")}</li>
          </ul>

          <h3>{t("assistant.step3.title")}</h3>
          <p>{t("assistant.step3.help")}</p>
          {prompt ? (
            <>
              <pre className="assistant-prompt" aria-label={t("assistant.prompt_label")}>
                {prompt}
              </pre>
              <CopyButton text={prompt} label={t("assistant.copy_prompt")} />
            </>
          ) : (
            <p role="alert">{t("assistant.prompt_error")}</p>
          )}
        </details>
        <p className="dim">{t("assistant.security")}</p>
      </section>
    </div>
  );
}
