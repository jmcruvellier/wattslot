// Discussion avec l'assistant de Home Assistant (page Assistant) : chaque message part vers un
// agent de conversation de HA (/api/assistant/chat), par défaut celui de l'assistant préféré ;
// en choisir un autre sert à le tester, sans rien changer dans HA. L'identifiant de conversation
// rendu par HA revient avec le message suivant. La conversation est gardée le temps de l'onglet
// du navigateur (sessionStorage) : on peut changer de page et revenir ; rien côté serveur.
// Les modèles d'Open WebUI configuré (Réglages, Assistant vocal) s'ajoutent à la liste
// (« open_webui:<modèle> ») ; l'historique de la page leur est renvoyé avec chaque message.

import { useEffect, useRef, useState } from "react";

import { ApiError, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n/translate";

interface Named {
  id: string;
  name: string;
}

interface AssistantHome {
  connected: boolean;
  pipelines: (Named & { conversation_engine: string | null })[];
  preferred_pipeline: string | null;
  agents: Named[];
}

interface ChatReply {
  text: string;
  conversation_id: string | null;
  error: boolean;
}

// Duration d'une réponse, en secondes (affichée à droite de la réponse).
type Line = { from: "me" | "assistant"; text: string; error?: boolean; duration?: number };

const OPEN_WEBUI = "open_webui:";

// Questions d'exemple, par thème, montrées tant que le fil est vide : chacune a sa réponse dans
// un outil du serveur MCP (assistant/tools.py côté serveur).
const EXAMPLES = {
  today: ["today", "next", "why", "now", "cost"],
  ahead: ["tomorrow", "sunniest", "off_peak"],
  measured: ["yesterday", "on_time"],
  requests: ["request", "requests", "problems"],
} as const;

// Conversation gardée le temps de l'onglet : fil, identifiant de HA, agent choisi.
const CHAT_KEY = "wattslot.chat";

interface SavedChat {
  lines: Line[];
  conversation: string | null;
  agent: string;
}

function savedChat(): SavedChat {
  try {
    const found = JSON.parse(window.sessionStorage.getItem(CHAT_KEY) ?? "null") as SavedChat | null;
    if (found && Array.isArray(found.lines)) return found;
  } catch {
    // stockage indisponible ou illisible : conversation neuve
  }
  return { lines: [], conversation: null, agent: "" };
}

function saveChat(chat: SavedChat) {
  try {
    window.sessionStorage.setItem(CHAT_KEY, JSON.stringify(chat));
  } catch {
    // stockage indisponible : la conversation vit le temps de la page
  }
}

export default function ChatCard({
  inputId,
  draft,
  onDraft,
}: {
  inputId: string;
  draft: string;
  onDraft: (text: string) => void;
}) {
  const { language, t } = useI18n();
  const [home, setHome] = useState<AssistantHome | null>(null);
  const [models, setModels] = useState<Named[]>([]);
  const [saved] = useState(savedChat);
  const [agent, setAgent] = useState(saved.agent);
  const [lines, setLines] = useState<Line[]>(saved.lines);
  const [conversation, setConversation] = useState<string | null>(saved.conversation);
  const [waiting, setWaiting] = useState(false);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    getJson<AssistantHome>("api/assistant/home", controller.signal)
      .then((found) => {
        setHome(found);
        const preferred = found.pipelines.find((p) => p.id === found.preferred_pipeline);
        // L'agent d'une conversation reprise est gardé ; sinon, celui de l'assistant préféré.
        setAgent((current) => current || (preferred?.conversation_engine ?? ""));
      })
      .catch(() => undefined);
    getJson<Named[]>("api/assistant/open-webui/models", controller.signal)
      .then(setModels)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    saveChat({ lines, conversation, agent });
  }, [lines, conversation, agent]);

  // La dernière réponse reste visible : le fil, de hauteur fixe, défile jusqu'en bas (sans faire
  // défiler la page).
  useEffect(() => {
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lines, waiting]);

  // Sans agent de HA (HA déconnecté), le premier modèle d'Open WebUI.
  const fallback = home && home.agents.length === 0 && models.length > 0 ? `${OPEN_WEBUI}${models[0].id}` : "";
  const chosen = agent || fallback;
  const preferredAgent = home?.pipelines.find((p) => p.id === home.preferred_pipeline)?.conversation_engine;

  const send = async () => {
    const text = draft.trim();
    if (!text || waiting) return;
    onDraft("");
    // Fil de la conversation pour Open WebUI, sans les messages d'erreur.
    const history = lines
      .filter((line) => !line.error)
      .map((line) => ({ role: line.from === "me" ? "user" : "assistant", content: line.text }));
    setLines((current) => [...current, { from: "me", text }]);
    setWaiting(true);
    const started = performance.now();
    try {
      const reply = await postJson<ChatReply>("api/assistant/chat", {
        text,
        agent_id: chosen || null,
        conversation_id: conversation,
        language,
        history: chosen.startsWith(OPEN_WEBUI) ? history.slice(-60) : [],
      });
      setConversation(reply.conversation_id);
      setLines((current) => [
        ...current,
        {
          from: "assistant",
          text: reply.text || t("assistant.chat.empty"),
          error: reply.error,
          duration: (performance.now() - started) / 1000,
        },
      ]);
    } catch (error) {
      const lost = error instanceof ApiError && error.status === 503 && !chosen.startsWith(OPEN_WEBUI);
      const key = lost ? "assistant.chat.not_connected" : "assistant.chat.failed";
      setLines((current) => [
        ...current,
        { from: "assistant", text: t(key), error: true, duration: (performance.now() - started) / 1000 },
      ]);
    } finally {
      setWaiting(false);
    }
  };

  const restart = () => {
    setLines([]);
    setConversation(null);
  };

  return (
    <section className="ui-card" aria-labelledby="assistant-chat-title">
      <div className="assistant-chat-head">
        <h2 id="assistant-chat-title" className="ui-card-title">
          {t("assistant.chat.title")}
        </h2>
        {lines.length > 0 && (
          <button type="button" onClick={restart}>
            {t("assistant.chat.restart")}
          </button>
        )}
      </div>

      {home?.connected === false && models.length === 0 && <p role="status">{t("assistant.chat.not_connected")}</p>}
      {((home && home.agents.length > 0) || models.length > 0) && (
        <p>
          <label htmlFor="assistant-chat-agent">{t("assistant.chat.agent")}</label>{" "}
          <select
            id="assistant-chat-agent"
            value={chosen}
            onChange={(event) => {
              // Un autre service ne connaît pas la conversation en cours : elle repart de zéro.
              if (event.target.value.startsWith(OPEN_WEBUI) !== chosen.startsWith(OPEN_WEBUI)) setConversation(null);
              setAgent(event.target.value);
            }}
          >
            {home && home.agents.length > 0 && (
              <optgroup label="Home Assistant">
                {!preferredAgent && <option value="">{t("assistant.chat.default_agent")}</option>}
                {home.agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.id === preferredAgent ? t("assistant.chat.preferred", { name: a.name }) : a.name}
                  </option>
                ))}
              </optgroup>
            )}
            {models.length > 0 && (
              <optgroup label="Open WebUI">
                {models.map((m) => (
                  <option key={m.id} value={`${OPEN_WEBUI}${m.id}`}>
                    {m.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </p>
      )}

      {/* Toujours là, de hauteur fixe : la carte ne grandit plus au fil des questions. */}
      <div className="assistant-chat-log" role="log" aria-live="polite" ref={log}>
        {lines.length === 0 && !waiting && (
          <div className="assistant-chat-empty">
            <p className="dim">{t("assistant.chat.log_empty")}</p>
            {/* Un clic remplit la zone de saisie : la question se corrige avant l'envoi. */}
            <h3>{t("assistant.examples.title")}</h3>
            {Object.entries(EXAMPLES).map(([group, keys]) => (
              <div key={group} className="assistant-examples-group">
                <h4 id={`assistant-examples-${group}`}>{t(`assistant.examples.groups.${group}`)}</h4>
                <ul className="assistant-examples" aria-labelledby={`assistant-examples-${group}`}>
                  {keys.map((key) => (
                    <li key={key}>
                      <button
                        type="button"
                        onClick={() => {
                          onDraft(t(`assistant.examples.${key}`));
                          document.getElementById(inputId)?.focus();
                        }}
                      >
                        {t(`assistant.examples.${key}`)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
        {lines.map((line, index) => (
          <p
            key={index}
            className={`assistant-chat-line assistant-chat-${line.from}`}
            data-error={line.error || undefined}
          >
            <span className="visually-hidden">
              {t(line.from === "me" ? "assistant.chat.you" : "assistant.chat.assistant")} :{" "}
            </span>
            {line.from === "assistant" && line.duration !== undefined && (
              <span className="assistant-chat-time dim">
                {t("assistant.chat.duration", {
                  time: formatNumber(language, line.duration, line.duration < 10 ? 1 : 0),
                })}
              </span>
            )}
            {line.text}
          </p>
        ))}
        {waiting && <p className="assistant-chat-line assistant-chat-assistant dim">{t("assistant.chat.thinking")}</p>}
      </div>

      <form
        className="assistant-chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label htmlFor={inputId} className="visually-hidden">
          {t("assistant.chat.input")}
        </label>
        <textarea
          id={inputId}
          rows={2}
          value={draft}
          placeholder={t("assistant.chat.placeholder")}
          onChange={(event) => onDraft(event.target.value)}
          onKeyDown={(event) => {
            // Entrée envoie, Maj+Entrée passe à la ligne.
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <button type="submit" disabled={waiting || !draft.trim()}>
          {t("assistant.chat.send")}
        </button>
      </form>
      <p className="dim">{t("assistant.chat.help")}</p>
    </section>
  );
}
