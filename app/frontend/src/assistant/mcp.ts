// Serveur MCP de l'application vu de la page : adresse à donner à Home Assistant, vérification
// qu'il répond (liste des outils). Partagé par la page Assistant et la sous-page « Assistant
// vocal » des Réglages ; les éléments d'affichage sont dans `McpParts`.

import { useCallback, useEffect, useState } from "react";

import { getJson } from "../api";

export interface Connection {
  mode: "addon" | "standalone";
  mcp_url: string | null;
}

export type Check = { status: "idle" | "checking" } | { status: "ok"; tools: number } | { status: "failed"; detail: string };

// URL relative : derrière l'ingress de HA, la page est servie sous un préfixe variable.
const MCP_URL = "mcp";
const ACCEPT = { "Content-Type": "application/json", Accept: "application/json, text/event-stream" };

/** Adresse que HA donnera à son intégration MCP : celle de l'extension sur le réseau interne,
 * sinon celle par laquelle le navigateur joint l'application. */
export function mcpAddress(connection: Connection | null): string {
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

/** Mode de l'application et adresse du serveur MCP (`null` tant qu'ils ne sont pas lus). */
export function useConnection(): Connection | null {
  const [connection, setConnection] = useState<Connection | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getJson<Connection>("api/assistant/connection", controller.signal)
      .then(setConnection)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  return connection;
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
