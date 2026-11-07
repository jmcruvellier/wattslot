// Bloc « Open WebUI » de la sous-page « Assistant vocal » : adresse et clé d'API pour discuter
// avec un modèle d'Open WebUI depuis la page Assistant (/api/assistant/open-webui), en liste de
// réglages. La clé ne revient jamais du serveur : la page sait seulement qu'il y en a une
// (« Clé enregistrée »). Elle ne vaut que pour son serveur : une adresse vers un autre serveur
// redemande la clé, que le serveur ne garde pas (open_webui.merged). `OpenWebUITools` : la ligne dépliable, rangée sous « Pour aller plus
// loin », qui explique comment donner les outils de WattSlot à Open WebUI lui-même.

import { useEffect, useState } from "react";

import { ApiError, getJson, postJson, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import Icon from "../ui/Icon";
import { SettingList } from "../ui/SettingRow";

interface OpenWebUIState {
  url: string | null;
  has_key: boolean;
}

type Test = { status: "idle" | "testing" } | { status: "ok"; count: number } | { status: "failed"; detail: string };
type Save = "idle" | "saving" | "saved" | "invalid" | "failed";

/** Schéma, hôte et port de l'adresse (`URL.host` omet le port par défaut) ; null si illisible. */
function serverOf(url: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? `${parsed.protocol}//${parsed.host}` : null;
  } catch {
    return null;
  }
}

function detailOf(error: unknown): string {
  if (error instanceof ApiError) return typeof error.detail === "string" ? error.detail : error.message;
  return error instanceof Error ? error.message : String(error);
}

export default function OpenWebUISettings() {
  const { t } = useI18n();
  const [saved, setSaved] = useState<OpenWebUIState | null>(null);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [test, setTest] = useState<Test>({ status: "idle" });
  const [save, setSave] = useState<Save>("idle");

  const show = (state: OpenWebUIState) => {
    setSaved(state);
    setUrl(state.url ?? "");
    setKey("");
    setReplacing(false);
  };

  useEffect(() => {
    const controller = new AbortController();
    getJson<OpenWebUIState>("api/assistant/open-webui", controller.signal)
      .then(show)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  if (!saved) return null;

  const form = (extra: object = {}) => ({ url: url.trim() || null, api_key: key || null, ...extra });
  const changed = () => {
    setSave("idle");
    setTest({ status: "idle" });
  };

  const put = async (body: object) => {
    setSave("saving");
    try {
      show(await putJson<OpenWebUIState>("api/assistant/open-webui", body));
      setSave("saved");
    } catch (error) {
      setSave(error instanceof ApiError && error.status === 422 ? "invalid" : "failed");
    }
  };

  const onTest = async () => {
    setTest({ status: "testing" });
    try {
      const models = await postJson<unknown[]>("api/assistant/open-webui/test", form());
      setTest({ status: "ok", count: models.length });
    } catch (error) {
      setTest({ status: "failed", detail: detailOf(error) });
    }
  };

  // Clé enregistrée pour un autre serveur que celui de l'adresse saisie : elle ne la suivra pas.
  const otherServer = saved.has_key && serverOf(url.trim()) !== serverOf(saved.url);
  const keyInput = !saved.has_key || replacing || otherServer;

  return (
    <>
      <h3 id="open-webui" className="home-summary-heading">
        {t("settings.open_webui.title")} <span className="settings-aside">· {t("settings.open_webui.optional")}</span>
      </h3>
      <SettingList>
        <div className="ui-setting-row">
          <span>
            <label className="ui-row-label" htmlFor="open-webui-url">
              {t("settings.open_webui.url")}
            </label>
            <span className="ui-row-help">{t("settings.open_webui.help")}</span>
          </span>
          <input
            id="open-webui-url"
            type="url"
            value={url}
            placeholder="http://192.0.2.10:3000"
            onChange={(event) => {
              changed();
              setUrl(event.target.value);
            }}
          />
        </div>
        {keyInput ? (
          <div className="ui-setting-row">
            <span>
              <label className="ui-row-label" htmlFor="open-webui-key">
                {t("settings.open_webui.key")}
              </label>
              {otherServer && !replacing && (
                <span className="ui-row-help">{t("settings.open_webui.key_other_server")}</span>
              )}
            </span>
            <input
              id="open-webui-key"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(event) => {
                changed();
                setKey(event.target.value);
              }}
            />
          </div>
        ) : (
          <div className="ui-setting-row">
            <span>
              <span className="ui-row-label">{t("settings.open_webui.key")}</span>
              <span className="ui-row-help">{t("settings.open_webui.key_saved")}</span>
            </span>
            <span className="settings-actions">
              <button type="button" onClick={() => setReplacing(true)}>
                {t("settings.open_webui.replace")}
              </button>
              <button
                type="button"
                className="ui-button-quiet settings-danger"
                disabled={save === "saving"}
                onClick={() => void put(form({ api_key: null, clear_key: true }))}
              >
                {t("settings.open_webui.clear")}
              </button>
            </span>
          </div>
        )}
        <div className="settings-foot">
          <span>
            {test.status === "ok" && (
              <span role="status" className="settings-ok">
                {t("settings.open_webui.test_ok", { count: test.count })}
              </span>
            )}
            {test.status === "failed" && (
              <span role="alert">{t("settings.open_webui.test_failed", { detail: test.detail })}</span>
            )}
            {save === "saved" && test.status === "idle" && (
              <span role="status" className="settings-ok">
                {t("settings.saved")}
              </span>
            )}
            {(save === "invalid" || save === "failed") && <span role="alert">{t(`settings.open_webui.${save}`)}</span>}
          </span>
          <span className="settings-actions">
            <button type="button" disabled={test.status === "testing" || !url.trim()} onClick={() => void onTest()}>
              {t(test.status === "testing" ? "settings.open_webui.testing" : "settings.open_webui.test")}
            </button>
            <button
              type="button"
              className="ui-button ui-button-primary"
              disabled={save === "saving"}
              onClick={() => void put(form())}
            >
              {t("settings.save")}
            </button>
          </span>
        </div>
      </SettingList>
    </>
  );
}

/** Ligne dépliable : comment ajouter le serveur MCP de WattSlot dans Open WebUI lui-même. */
export function OpenWebUITools({ mode }: { mode: "addon" | "standalone" | null }) {
  const { t } = useI18n();
  return (
    <details className="ui-setting-row settings-details">
      <summary>
        <span>
          <span className="ui-row-label">{t("settings.open_webui.tools")}</span>
          <span className="ui-row-help">{t("settings.open_webui.tools_help")}</span>
        </span>
        <Icon name="chevron-right" size={18} />
      </summary>
      <p>{t("settings.open_webui.tools_page")}</p>
      <ol>
        <li>{t("settings.open_webui.tools_server")}</li>
        <li>{t("settings.open_webui.tools_model")}</li>
      </ol>
      <p className="dim">
        {t(mode === "addon" ? "settings.open_webui.tools_addon" : "settings.open_webui.tools_standalone")}
      </p>
    </details>
  );
}
