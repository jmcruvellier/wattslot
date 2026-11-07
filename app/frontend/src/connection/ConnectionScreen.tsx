// Connexion à Home Assistant en mode autonome (lot 4.6) : « Se connecter avec Home Assistant »
// (OAuth2 de HA), repli sur un jeton d'accès longue durée, déconnexion. L'application redémarre
// pour appliquer une connexion : la page attend qu'elle réponde à nouveau. En mode extension, ou
// si les variables d'environnement fixent la connexion, elle ne se change pas ici. Présentation
// des sous-pages des Réglages : l'état en carte, puis des listes.

import { useEffect, useRef, useState } from "react";

import { ApiError, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { refreshStatus } from "../nav/status";
import Icon from "../ui/Icon";
import { SettingList } from "../ui/SettingRow";
import { applicationAddress } from "./address";
import { connectionError, retryConnection, type ConnectionInfo } from "./service";

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
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getJson<ConnectionInfo>("api/connection", controller.signal)
      .then((info) => {
        setLoad({ status: "ready", info });
        // Sans connexion, l'adresse de HA_URL (commande Docker du README) est proposée.
        if (info.source === null && info.url) setUrl(info.url);
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, []);

  // Écran quitté : l'attente du redémarrage s'arrête (elle rechargeait sinon l'application
  // depuis un autre écran, jusqu'à RESTART_WAIT_MS plus tard).
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Redémarrage : l'application cesse de répondre puis revient ; on recharge alors la page.
  const waitForRestart = async () => {
    setAction("restarting");
    const started = Date.now();
    await new Promise((resolve) => window.setTimeout(resolve, 2 * POLL_MS));
    while (mounted.current && Date.now() - started < RESTART_WAIT_MS) {
      try {
        const response = await fetch("api/health");
        if (response.ok && mounted.current) {
          window.location.assign(applicationAddress());
          return;
        }
      } catch {
        // pas encore revenue
      }
      await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
    }
    if (mounted.current) setAction("timeout");
  };

  const reason = (error: unknown) =>
    error instanceof ApiError && typeof error.detail === "string" ? error.detail : "failed";

  // Reconnexion immédiate demandée à l'application : l'état est relu après la tentative.
  const retry = async () => {
    setChecking(true);
    const info = await retryConnection();
    if (info) setLoad({ status: "ready", info });
    setChecking(false);
    refreshStatus();
  };

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
  // Pastille : mêmes couleurs que l'état de l'application.
  const level = info.state === "connected" ? "ok" : info.state === "error" ? "blocking" : "setup";
  const detail =
    info.state === "error"
      ? connectionError(t, info.error_code)
      : info.source === "saved"
        ? t(`connection_page.saved.${info.method ?? "token"}`, { url: info.url ?? "" })
        : info.source === "supervisor"
          ? t("connection_page.addon")
          : info.source === "env"
            ? t("connection_page.environment")
            : null;

  return (
    <section className="settings-page" aria-labelledby="connection-title">
      <h2 className="visually-hidden" id="connection-title">{t("connection_page.title")}</h2>

      <div className="ui-card settings-state">
        <span className="status-dot" data-level={level} aria-hidden="true" />
        <span className="settings-state-text">
          <span className="ui-row-label">
            {t("connection_page.state")} {t(`connection.${info.state}`)}
          </span>
          {detail && <span className="ui-row-help">{detail}</span>}
        </span>
        {info.state === "error" && (
          <button type="button" className="ui-button ui-button-quiet" disabled={checking} onClick={() => void retry()}>
            {t(checking ? "connection_page.checking" : "connection_page.retry")}
          </button>
        )}
      </div>
      {returned && (
        <p role="status" className="settings-note">
          {t(`connection_page.returned.${returned}`)}
        </p>
      )}
      {action === "restarting" && (
        <p role="status" className="settings-note">
          {t("connection_page.restarting")}
        </p>
      )}
      {action === "timeout" && (
        <p role="alert" className="settings-note">
          {t("connection_page.timeout")}
        </p>
      )}
      {failure && (
        <p role="alert" className="settings-note">
          {t(`connection_page.failure.${failure}`)}
        </p>
      )}

      {info.source === "saved" && (
        <>
          <h3 className="home-summary-heading">{t("connection_page.saved_title")}</h3>
          <SettingList>
            <div className="ui-setting-row">
              <span>
                <span className="ui-row-label">{t("connection_page.url")}</span>
                <span className="ui-row-help">{info.url}</span>
              </span>
              <button
                type="button"
                className="ui-button-quiet settings-danger"
                disabled={busy}
                onClick={() => void disconnect()}
              >
                {t("connection_page.disconnect")}
              </button>
            </div>
          </SettingList>
        </>
      )}

      {info.source === null && (
        <>
          <h3 className="home-summary-heading">{t("connection_page.connect_title")}</h3>
          <p className="settings-note settings-intro">{t("connection_page.intro")}</p>
          <SettingList>
            <div className="ui-setting-row">
              <span>
                <label className="ui-row-label" htmlFor="ha-url">
                  {t("connection_page.url")}
                </label>
                <span className="ui-row-help">{t("connection_page.url_hint")}</span>
              </span>
              <input
                id="ha-url"
                type="url"
                value={url}
                placeholder="http://homeassistant.local:8123"
                onChange={(event) => setUrl(event.target.value.trim())}
              />
            </div>
            <div className="settings-foot">
              <span />
              <button
                type="button"
                className="ui-button ui-button-primary"
                disabled={busy || url === ""}
                onClick={() => void withHomeAssistant()}
              >
                {t("connection_page.oauth")}
              </button>
            </div>
          </SettingList>

          <h3 className="home-summary-heading">{t("nav.more")}</h3>
          <SettingList>
            <details className="ui-setting-row settings-details">
              <summary>
                <span>
                  <span className="ui-row-label">{t("connection_page.token_title")}</span>
                  <span className="ui-row-help">{t("connection_page.token_help")}</span>
                </span>
                <Icon name="chevron-right" size={18} />
              </summary>
              <div className="ui-setting-row">
                <label className="ui-row-label" htmlFor="ha-token">
                  {t("connection_page.token")}
                </label>
                <span className="settings-actions">
                  <input
                    id="ha-token"
                    type="password"
                    value={token}
                    onChange={(event) => setToken(event.target.value.trim())}
                  />
                  <button
                    type="button"
                    disabled={busy || url === "" || token === ""}
                    onClick={() => void withToken()}
                  >
                    {t("connection_page.connect_token")}
                  </button>
                </span>
              </div>
            </details>
          </SettingList>
        </>
      )}

      {info.source !== "supervisor" && <p className="settings-note">{t("connection_page.security")}</p>}
    </section>
  );
}
