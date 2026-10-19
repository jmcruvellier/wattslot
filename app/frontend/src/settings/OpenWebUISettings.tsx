// Bloc « Open WebUI » de la sous-page « Assistant vocal » : adresse et clé d'API pour discuter
// avec un modèle d'Open WebUI depuis la page Assistant (/api/assistant/open-webui). La clé ne
// revient jamais du serveur : la page sait seulement qu'il y en a une (« Clé enregistrée »).

import { useEffect, useState } from "react";

import { ApiError, getJson, postJson, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";

interface OpenWebUIState {
  url: string | null;
  has_key: boolean;
}

type Test = { status: "idle" | "testing" } | { status: "ok"; count: number } | { status: "failed"; detail: string };
type Save = "idle" | "saving" | "saved" | "invalid" | "failed";

function detailOf(error: unknown): string {
  if (error instanceof ApiError) return typeof error.detail === "string" ? error.detail : error.message;
  return error instanceof Error ? error.message : String(error);
}

export default function OpenWebUISettings({ mode }: { mode: "addon" | "standalone" | null }) {
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

  const keyInput = !saved.has_key || replacing;

  return (
    <>
      <h3 id="open-webui">{t("settings.open_webui.title")}</h3>
      <p>{t("settings.open_webui.help")}</p>
      <p>
        <label htmlFor="open-webui-url">{t("settings.open_webui.url")}</label>{" "}
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
      </p>
      {keyInput ? (
        <p>
          <label htmlFor="open-webui-key">{t("settings.open_webui.key")}</label>{" "}
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
        </p>
      ) : (
        <p>
          {t("settings.open_webui.key")} : {t("settings.open_webui.key_saved")}{" "}
          <button type="button" onClick={() => setReplacing(true)}>
            {t("settings.open_webui.replace")}
          </button>{" "}
          <button type="button" disabled={save === "saving"} onClick={() => void put(form({ api_key: null, clear_key: true }))}>
            {t("settings.open_webui.clear")}
          </button>
        </p>
      )}
      <p>
        <button type="button" disabled={test.status === "testing" || !url.trim()} onClick={() => void onTest()}>
          {t(test.status === "testing" ? "settings.open_webui.testing" : "settings.open_webui.test")}
        </button>{" "}
        <button type="button" disabled={save === "saving"} onClick={() => void put(form())}>
          {t("settings.save")}
        </button>
      </p>
      {test.status === "ok" && <p role="status">{t("settings.open_webui.test_ok", { count: test.count })}</p>}
      {test.status === "failed" && <p role="alert">{t("settings.open_webui.test_failed", { detail: test.detail })}</p>}
      {save === "saved" && <p role="status">{t("settings.saved")}</p>}
      {(save === "invalid" || save === "failed") && <p role="alert">{t(`settings.open_webui.${save}`)}</p>}

      <details className="plan-more">
        <summary>{t("settings.open_webui.tools")}</summary>
        <ol>
          <li>{t("settings.open_webui.tools_server")}</li>
          <li>{t("settings.open_webui.tools_model")}</li>
        </ol>
        <p className="dim">
          {t(mode === "addon" ? "settings.open_webui.tools_addon" : "settings.open_webui.tools_standalone")}
        </p>
      </details>
    </>
  );
}
