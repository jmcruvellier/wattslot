// Sous-page « Assistant vocal » des Réglages : l'état du serveur MCP (comme la page Assistant),
// la configuration lue dans Home Assistant (adresse du serveur, intégration MCP), et le choix de
// l'assistant préféré de HA avec son agent de conversation (/api/assistant/home). L'application
// ne garde aucun réglage de l'assistant de HA : « Enregistrer » le modifie dans HA. En bas,
// Open WebUI en appel direct (`OpenWebUISettings`).

import { useEffect, useState } from "react";

import { ApiError, getJson, putJson } from "../api";
import { checkTitle, useConnection, useMcpCheck } from "../assistant/mcp";
import { CheckResult, McpAddress } from "../assistant/McpParts";
import { useI18n } from "../i18n/I18nProvider";
import { routeHash } from "../nav/routes";
import StateMessage from "../ui/StateMessage";
import OpenWebUISettings from "./OpenWebUISettings";

interface Named {
  id: string;
  name: string;
}

interface AssistantHome {
  connected: boolean;
  mcp: { title: string; state: string }[];
  pipelines: (Named & { conversation_engine: string | null })[];
  preferred_pipeline: string | null;
  agents: Named[];
}

type Load = { status: "loading" } | { status: "error" } | { status: "ready"; home: AssistantHome };
type Save = "idle" | "saving" | "saved" | "invalid" | "failed";

// États d'une entrée de configuration de HA, regroupés pour l'affichage.
function mcpState(state: string): "loaded" | "error" | "not_loaded" {
  if (state === "loaded") return "loaded";
  if (state === "not_loaded") return "not_loaded";
  return "error";
}

export default function VoiceSettings() {
  const { t } = useI18n();
  const [connection, setConnection] = useConnection();
  const [check, verify] = useMcpCheck();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0); // « Réessayer »
  const [pipeline, setPipeline] = useState<string>("");
  const [agent, setAgent] = useState<string>("");
  const [save, setSave] = useState<Save>("idle");

  const show = (home: AssistantHome) => {
    const preferred = home.pipelines.find((p) => p.id === home.preferred_pipeline) ?? home.pipelines[0];
    setLoad({ status: "ready", home });
    setPipeline(preferred?.id ?? "");
    setAgent(preferred?.conversation_engine ?? "");
  };

  useEffect(() => {
    const controller = new AbortController();
    getJson<AssistantHome>("api/assistant/home", controller.signal)
      .then(show)
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [attempt]);


  const onSave = async () => {
    setSave("saving");
    try {
      show(await putJson<AssistantHome>("api/assistant/home", { pipeline_id: pipeline, conversation_engine: agent }));
      setSave("saved");
    } catch (error) {
      setSave(error instanceof ApiError && error.status === 422 ? "invalid" : "failed");
    }
  };

  return (
    <section aria-labelledby="voice-title">
      <h2 id="voice-title" className="visually-hidden">
        {t("nav.voice")}
      </h2>

      <h3>{t("settings.voice.state")}</h3>
      <p>{t(checkTitle(check))}</p>
      <CheckResult check={check} onVerify={() => void verify()} />

      <h3>{t("settings.voice.current")}</h3>
      <p>{t("settings.voice.address")}</p>
      <McpAddress connection={connection} onChange={setConnection} />
      <p className="dim">{t(connection?.mode === "addon" ? "assistant.step1.addon" : "assistant.step1.standalone")}</p>

      {load.status === "loading" && <StateMessage kind="loading" title={t("settings.loading")} />}
      {load.status === "error" && (
        <StateMessage
          kind="error"
          title={t("settings.error")}
          onRetry={() => {
            setLoad({ status: "loading" });
            setAttempt((count) => count + 1);
          }}
        />
      )}
      {load.status === "ready" && (
        <HomeAssistantPart
          home={load.home}
          pipeline={pipeline}
          agent={agent}
          save={save}
          onPipeline={(id) => {
            setSave("idle");
            setPipeline(id);
            setAgent(load.home.pipelines.find((p) => p.id === id)?.conversation_engine ?? "");
          }}
          onAgent={(id) => {
            setSave("idle");
            setAgent(id);
          }}
          onSave={() => void onSave()}
        />
      )}

      <OpenWebUISettings mode={connection?.mode ?? null} />

      <p>
        <a href={routeHash({ section: "assistant", sub: null })}>{t("assistant.setup")}</a>
      </p>
    </section>
  );
}

function HomeAssistantPart({
  home,
  pipeline,
  agent,
  save,
  onPipeline,
  onAgent,
  onSave,
}: {
  home: AssistantHome;
  pipeline: string;
  agent: string;
  save: Save;
  onPipeline: (id: string) => void;
  onAgent: (id: string) => void;
  onSave: () => void;
}) {
  const { t } = useI18n();
  if (!home.connected) return <p role="status">{t("settings.voice.not_connected")}</p>;
  // Agent actuel que HA ne liste plus (intégration supprimée) : gardé dans la liste.
  const agents =
    agent && !home.agents.some((a) => a.id === agent) ? [...home.agents, { id: agent, name: agent }] : home.agents;
  return (
    <>
      <p>
        {t("settings.voice.mcp")} :{" "}
        {home.mcp.length === 0
          ? t("settings.voice.mcp_none")
          : home.mcp
              .map((entry) => t("settings.voice.mcp_entry", { title: entry.title, state: t(`settings.voice.mcp_states.${mcpState(entry.state)}`) }))
              .join(", ")}
      </p>

      <h3>{t("settings.voice.home")}</h3>
      <p>{t("settings.voice.home_help")}</p>
      {home.pipelines.length === 0 ? (
        <p>{t("settings.voice.no_pipeline")}</p>
      ) : (
        <>
          <p>
            <label htmlFor="voice-pipeline">{t("settings.voice.pipeline")}</label>{" "}
            <select id="voice-pipeline" value={pipeline} onChange={(event) => onPipeline(event.target.value)}>
              {home.pipelines.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </p>
          <p>
            <label htmlFor="voice-agent">{t("settings.voice.agent")}</label>{" "}
            <select id="voice-agent" value={agent} onChange={(event) => onAgent(event.target.value)}>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </p>
          <p>
            <button type="button" disabled={save === "saving" || !agent} onClick={onSave}>
              {t("settings.save")}
            </button>
          </p>
          {save === "saved" && <p role="status">{t("settings.voice.saved")}</p>}
          {(save === "invalid" || save === "failed") && <p role="alert">{t(`settings.voice.${save}`)}</p>}
        </>
      )}
    </>
  );
}
