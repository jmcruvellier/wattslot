// Serveur MCP de l'application vu de la page : adresse à donner à Home Assistant, vérification
// qu'il répond (liste des outils). Partagé par la page Assistant et la sous-page « Assistant
// vocal » des Réglages ; les éléments d'affichage sont dans `McpParts`.

import { useCallback, useEffect, useState } from "react";

import { getJson, putJson } from "../api";

export interface Connection {
  mode: "addon" | "standalone";
  mcp_url: string | null;
  saved?: boolean; // adresse retenue par l'application (depuis le réseau local, ou corrigée)
}

export type Check = { status: "idle" | "checking" } | { status: "ok"; tools: number } | { status: "failed"; detail: string };

// URL relative : derrière l'ingress de HA, la page est servie sous un préfixe variable.
const MCP_URL = "mcp";
const ACCEPT = { "Content-Type": "application/json", Accept: "application/json, text/event-stream" };

// Le serveur MCP n'est appelé que sur le réseau local (HA, Open WebUI) : l'adresse du navigateur
// ne vaut que si la page est ouverte depuis ce réseau.
const PRIVATE = [/^localhost$/, /^127\./, /^10\./, /^192\.168\./, /^172\.(1[6-9]|2\d|3[01])\./, /\.local$/, /^\[::1\]$/];

function browserAddress(): string | null {
  const host = window.location.hostname;
  const local = PRIVATE.some((pattern) => pattern.test(host)) || !host.includes(".");
  return local ? new URL(MCP_URL, window.location.href.replace(/[?#].*$/, "")).href : null;
}

/** Adresse que HA donnera à son intégration MCP : celle retenue par l'application ou celle de
 * l'extension sur le réseau interne, sinon celle du navigateur ouvert depuis le réseau local ;
 * `null` depuis l'extérieur tant qu'aucune n'est retenue. */
export function mcpAddress(connection: Connection | null): string | null {
  if (connection?.mcp_url) return connection.mcp_url;
  return browserAddress();
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

/** Mode de l'application et adresse du serveur MCP (`null` tant qu'ils ne sont pas lus). Page
 * ouverte depuis le réseau local, sans adresse connue : celle du navigateur est retenue. */
export function useConnection(): [Connection | null, (connection: Connection) => void] {
  const [connection, setConnection] = useState<Connection | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getJson<Connection>("api/assistant/connection", controller.signal)
      .then(async (found) => {
        const local = browserAddress();
        if (!found.mcp_url && local) {
          found = await putJson<Connection>("api/assistant/connection", { mcp_url: local }).catch(() => found);
        }
        if (!controller.signal.aborted) setConnection(found);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  return [connection, setConnection];
}

/** Vérification du serveur MCP, lancée à l'ouverture (lot 6b.6) ; `verify` la relance. */
export function useMcpCheck(): [Check, () => Promise<void>] {
  const [check, setCheck] = useState<Check>({ status: "idle" });

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

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void verify();
    });
    return () => {
      active = false;
    };
  }, [verify]);

  return [check, verify];
}

/** Clé du titre qui résume l'état du serveur. */
export function checkTitle(check: Check): string {
  if (check.status === "ok") return "assistant.state.ready";
  if (check.status === "failed") return "assistant.state.down";
  return "assistant.state.checking";
}
