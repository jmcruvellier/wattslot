// Connexion à Home Assistant en mode autonome (lot 4.6) : « Se connecter avec Home Assistant »
// (OAuth2 de HA), repli sur un jeton d'accès longue durée, déconnexion. L'application redémarre
// pour appliquer une connexion : la page attend qu'elle réponde à nouveau. En mode extension, ou
// si les variables d'environnement fixent la connexion, elle ne se change pas ici.

import { useEffect, useState } from "react";

import { ApiError, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { applicationAddress } from "./address";

export interface ConnectionInfo {
  mode: "addon" | "standalone";
  source: "supervisor" | "env" | "saved" | null;
  url: string | null;
  method: "oauth" | "token" | null;
  state: "not_configured" | "connecting" | "connected" | "error";
  error: string | null;
}

type Load = { status: "loading" } | { status: "error" } | { status: "ready"; info: ConnectionInfo };
type Action = "idle" | "working" | "restarting" | "timeout";

const RESTART_WAIT_MS = 60_000;
const POLL_MS = 1_000;

export default function ConnectionScreen({ returned }: { returned: string | null }) {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [action, setAction] = useState<Action>("idle");
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getJson<ConnectionInfo>("api/connection", controller.signal)
      .then((info) => setLoad({ status: "ready", info }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, []);

  // Redémarrage : l'application cesse de répondre puis revient ; on recharge alors la page.
  const waitForRestart = async () => {
    setAction("restarting");
    const started = Date.now();
    await new Promise((resolve) => window.setTimeout(resolve, 2 * POLL_MS));
    while (Date.now() - started < RESTART_WAIT_MS) {
      try {
        const response = await fetch("api/health");
        if (response.ok) {
          window.location.assign(applicationAddress());
          return;
        }
      } catch {
        // pas encore revenue
      }
      await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
    }
    setAction("timeout");
  };

  const reason = (error: unknown) =>
    error instanceof ApiError && typeof error.detail === "string" ? error.detail : "failed";

  const withHomeAssistant = async () => {
    setAction("working");
    setFailure(null);
    try {
      const found = await postJson<{ authorize_url: string }>("api/connection/oauth", {
        url,
        client_id: applicationAddress(),
      });
      window.location.assign(found.authorize_url);
    } catch (error) {
      setFailure(reason(error));
      setAction("idle");
    }
  };

  const withToken = async () => {
    setAction("working");
    setFailure(null);
    try {
      await postJson("api/connection/token", { url, token });
      await waitForRestart();
    } catch (error) {
      setFailure(reason(error));
      setAction("idle");
    }
  };

  const disconnect = async () => {
    setAction("working");
    setFailure(null);
    try {
      const response = await fetch("api/connection", { method: "DELETE" });
      if (!response.ok) throw new ApiError(response.status);
      await waitForRestart();
    } catch (error) {
      setFailure(reason(error));
      setAction("idle");
    }
  };

  if (load.status === "loading") return <p>{t("connection_page.loading")}</p>;
  if (load.status === "error") return <p role="alert">{t("connection_page.error")}</p>;
  const { info } = load;
  const busy = action !== "idle";

  return (
    <section aria-labelledby="connection-title">
      <h2 className="visually-hidden" id="connection-title">{t("connection_page.title")}</h2>
      {returned && <p role="status">{t(`connection_page.returned.${returned}`)}</p>}
      <p>
        {t("connection_page.state")} <strong>{t(`connection.${info.state}`)}</strong>
        {info.error && <> — {info.error}</>}
      </p>
      {action === "restarting" && <p role="status">{t("connection_page.restarting")}</p>}
      {action === "timeout" && <p role="alert">{t("connection_page.timeout")}</p>}
      {failure && <p role="alert">{t(`connection_page.failure.${failure}`)}</p>}

      {info.source === "supervisor" && <p>{t("connection_page.addon")}</p>}
      {info.source === "env" && <p>{t("connection_page.environment")}</p>}

      {info.source === "saved" && (
        <>
          <p>
            {t(`connection_page.saved.${info.method ?? "token"}`, { url: info.url ?? "" })}
          </p>
          <button type="button" disabled={busy} onClick={() => void disconnect()}>
            {t("connection_page.disconnect")}
          </button>
        </>
      )}

      {info.source === null && (
        <>
          <p>{t("connection_page.intro")}</p>
          <p>
            <label>
              {t("connection_page.url")}{" "}
              <input
                type="url"
                value={url}
                placeholder="http://homeassistant.local:8123"
                onChange={(event) => setUrl(event.target.value.trim())}
              />
            </label>
            <br />
            <small>{t("connection_page.url_hint")}</small>
          </p>
          <button type="button" disabled={busy || url === ""} onClick={() => void withHomeAssistant()}>
            {t("connection_page.oauth")}
          </button>
          <details>
            <summary>{t("connection_page.token_title")}</summary>
            <p>{t("connection_page.token_help")}</p>
            <label>
              {t("connection_page.token")}{" "}
              <input type="password" value={token} onChange={(event) => setToken(event.target.value.trim())} />
            </label>{" "}
            <button type="button" disabled={busy || url === "" || token === ""} onClick={() => void withToken()}>
              {t("connection_page.connect_token")}
            </button>
          </details>
          <p>
            <small>{t("connection_page.security")}</small>
          </p>
        </>
      )}
    </section>
  );
}
