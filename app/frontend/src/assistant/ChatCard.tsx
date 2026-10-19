// Discussion avec l'assistant de Home Assistant (page Assistant) : chaque message part vers un
// agent de conversation de HA (/api/assistant/chat), par défaut celui de l'assistant préféré ;
// en choisir un autre sert à le tester, sans rien changer dans HA. L'identifiant de conversation
// rendu par HA revient avec le message suivant ; rien n'est enregistré (perdu au rechargement).

import { useEffect, useRef, useState } from "react";

import { ApiError, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";

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

type Line = { from: "me" | "assistant"; text: string; error?: boolean };

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
  const [agent, setAgent] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    getJson<AssistantHome>("api/assistant/home", controller.signal)
      .then((found) => {
        setHome(found);
        const preferred = found.pipelines.find((p) => p.id === found.preferred_pipeline);
        setAgent(preferred?.conversation_engine ?? "");
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  // La dernière réponse reste visible.
  useEffect(() => {
    log.current?.lastElementChild?.scrollIntoView?.({ block: "nearest" });
  }, [lines, waiting]);

  const preferredAgent = home?.pipelines.find((p) => p.id === home.preferred_pipeline)?.conversation_engine;

  const send = async () => {
    const text = draft.trim();
    if (!text || waiting) return;
    onDraft("");
    setLines((current) => [...current, { from: "me", text }]);
    setWaiting(true);
    try {
      const reply = await postJson<ChatReply>("api/assistant/chat", {
        text,
        agent_id: agent || null,
        conversation_id: conversation,
        language,
      });
      setConversation(reply.conversation_id);
      setLines((current) => [
        ...current,
        { from: "assistant", text: reply.text || t("assistant.chat.empty"), error: reply.error },
      ]);
    } catch (error) {
      const key = error instanceof ApiError && error.status === 503 ? "assistant.chat.not_connected" : "assistant.chat.failed";
      setLines((current) => [...current, { from: "assistant", text: t(key), error: true }]);
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

      {home?.connected === false && <p role="status">{t("assistant.chat.not_connected")}</p>}
      {home && home.agents.length > 0 && (
        <p>
          <label htmlFor="assistant-chat-agent">{t("assistant.chat.agent")}</label>{" "}
          <select id="assistant-chat-agent" value={agent} onChange={(event) => setAgent(event.target.value)}>
            {!preferredAgent && <option value="">{t("assistant.chat.default_agent")}</option>}
            {home.agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.id === preferredAgent ? t("assistant.chat.preferred", { name: a.name }) : a.name}
              </option>
            ))}
          </select>
        </p>
      )}

      {(lines.length > 0 || waiting) && (
        <div className="assistant-chat-log" role="log" aria-live="polite" ref={log}>
          {lines.map((line, index) => (
            <p
              key={index}
              className={`assistant-chat-line assistant-chat-${line.from}`}
              data-error={line.error || undefined}
            >
              <span className="visually-hidden">
                {t(line.from === "me" ? "assistant.chat.you" : "assistant.chat.assistant")} :{" "}
              </span>
              {line.text}
            </p>
          ))}
          {waiting && <p className="assistant-chat-line assistant-chat-assistant dim">{t("assistant.chat.thinking")}</p>}
        </div>
      )}

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
