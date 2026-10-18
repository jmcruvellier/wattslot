// Page « Assistant » (lot 6.3) : brancher l'Assist de Home Assistant sur le serveur MCP de
// l'application, avec le LLM qu'on a déjà. Adresse du serveur à copier (selon le mode), réglages
// de l'agent de conversation, prompt conseillé, vérification que le serveur répond. Lot 6b.6 :
// en cartes, l'état d'abord (vérifié à l'ouverture), le branchement replié une fois vérifié.

import { useCallback, useEffect, useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import RequestsSection from "../start/RequestsSection";

interface Connection {
  mode: "addon" | "standalone";
  mcp_url: string | null;
}

interface AssistantPrompt {
  language: string;
  prompt: string;
}

type Check = { status: "idle" | "checking" } | { status: "ok"; tools: number } | { status: "failed"; detail: string };

// URL relative : derrière l'ingress de HA, la page est servie sous un préfixe variable.
const MCP_URL = "mcp";
const ACCEPT = { "Content-Type": "application/json", Accept: "application/json, text/event-stream" };

/** Adresse que HA donnera à son intégration MCP : celle de l'extension sur le réseau interne,
 * sinon celle par laquelle le navigateur joint l'application. */
function mcpAddress(connection: Connection | null): string {
  if (connection?.mcp_url) return connection.mcp_url;
  return new URL(MCP_URL, window.location.href.replace(/[?#].*$/, "")).href;
}

async function rpc(method: string, id: number, params: object = {}): Promise<Record<string, unknown>> {
  const response = await fetch(MCP_URL, {
    method: "POST",
    headers: ACCEPT,
    body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = (await response.json()) as { result?: Record<string, unknown>; error?: { message?: string } };
  if (!body.result) throw new Error(body.error?.message ?? "no result");
  return body.result;
}

function CopyButton({ text, label }: { text: string; label: string }) {
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

export default function AssistantScreen() {
  const { language, t } = useI18n();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [check, setCheck] = useState<Check>({ status: "idle" });

  useEffect(() => {
    const controller = new AbortController();
    getJson<Connection>("api/assistant/connection", controller.signal)
      .then(setConnection)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getJson<AssistantPrompt>(`api/assistant/prompt?lang=${language}`, controller.signal)
      .then((found) => setPrompt(found.prompt))
      .catch(() => setPrompt(null));
    return () => controller.abort();
  }, [language]);

  const verify = useCallback(async () => {
    setCheck({ status: "checking" });
    try {
      await rpc("initialize", 1, {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "wattslot-page", version: "1" },
      });
      const listed = await rpc("tools/list", 2);
      setCheck({ status: "ok", tools: Array.isArray(listed.tools) ? listed.tools.length : 0 });
    } catch (error) {
      setCheck({ status: "failed", detail: error instanceof Error ? error.message : String(error) });
    }
  }, []);

  // Vérifié à l'ouverture (lot 6b.6) : l'état de l'assistant s'affiche sans rien demander.
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void verify();
    });
    return () => {
      active = false;
    };
  }, [verify]);

  const address = mcpAddress(connection);
  const title =
    check.status === "ok"
      ? "assistant.state.ready"
      : check.status === "failed"
        ? "assistant.state.down"
        : "assistant.state.checking";
  // « Mes demandes » d'abord (lot 6b.3), puis l'assistant vocal (lot 6b.6) : son état, des
  // exemples de questions, et le branchement pas à pas, replié une fois le serveur vérifié.
  return (
    <div className="assistant">
      <div className="ui-card">
        <RequestsSection />
      </div>
      <section className="ui-card" aria-labelledby="assistant-title">
        <p className="ui-eyebrow">{t("assistant.title")}</p>
        <h2 id="assistant-title" className="ui-card-title">
          {t(title)}
        </h2>
        <p>{t("assistant.intro")}</p>
        {check.status === "ok" && <p role="status">{t("assistant.check.ok", { tools: check.tools })}</p>}
        {check.status === "failed" && <p role="alert">{t("assistant.check.failed", { detail: check.detail })}</p>}
        <p>
          <button type="button" disabled={check.status === "checking"} onClick={() => void verify()}>
            {t(check.status === "checking" ? "assistant.check.checking" : "assistant.check.run")}
          </button>
        </p>

        <h3>{t("assistant.examples.title")}</h3>
        <ul>
          <li>{t("assistant.examples.why")}</li>
          <li>{t("assistant.examples.yesterday")}</li>
          <li>{t("assistant.examples.battery")}</li>
          <li>{t("assistant.examples.request")}</li>
        </ul>

        <details className="plan-more" open={check.status !== "ok" || undefined}>
          <summary>{t("assistant.setup")}</summary>
          <h3>{t("assistant.step1.title")}</h3>
          <p>{t("assistant.step1.help")}</p>
          <p>
            <code className="assistant-address">{address}</code>{" "}
            <CopyButton text={address} label={t("assistant.copy_address")} />
          </p>
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
