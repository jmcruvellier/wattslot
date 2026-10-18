// Vue en graphe du modèle de la maison (lot 2t.3), en lecture seule : React Flow, chargé à la
// demande depuis l'onglet Maison. Un clic sur un nœud montre ses propriétés et ses anomalies.
// Sur un écran étroit (téléphone), une liste remplace le graphe.

import "@xyflow/react/dist/style.css";

import { Background, Controls, type Edge, type Node, ReactFlow } from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";

import { getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import type { Configuration, ConfigurationIssue } from "./configuration";
import { buildGraph, COLUMN_WIDTH, type Graph, type GraphNode, ROW_HEIGHT } from "./graph";
import type { DeviceTypes, HomeModel } from "./types";

const NARROW = "(max-width: 700px)";

type Load = { status: "loading" } | { status: "ready"; graph: Graph } | { status: "error" };

function narrowScreen(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(NARROW).matches;
}

export default function HomeGraph() {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [narrow] = useState(narrowScreen);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<HomeModel>("api/home", controller.signal),
      getJson<DeviceTypes>("api/home/types", controller.signal),
      getJson<Configuration>("api/configuration", controller.signal),
    ])
      .then(async ([home, types, configuration]) => {
        const check = await postJson<{ issues: ConfigurationIssue[] }>("api/configuration/validate", configuration);
        setLoad({ status: "ready", graph: buildGraph(home, types.types, check.issues, t) });
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [t]);

  const flow = useMemo(() => {
    if (load.status !== "ready") return { nodes: [] as Node[], edges: [] as Edge[] };
    return {
      nodes: load.graph.nodes.map(
        (node): Node => ({
          id: node.id,
          position: { x: node.column * COLUMN_WIDTH, y: node.row * ROW_HEIGHT },
          data: { label: node.issues.length ? `⚠ ${node.label}` : node.label },
          className: `graph-node graph-${node.kind}`,
        }),
      ),
      edges: load.graph.edges.map((edge): Edge => ({ ...edge })),
    };
  }, [load]);

  if (load.status === "loading") return <p>{t("graph.loading")}</p>;
  if (load.status === "error") return <p role="alert">{t("graph.error")}</p>;
  const { graph } = load;
  if (graph.nodes.length === 0) return <p>{t("graph.empty")}</p>;

  if (narrow) {
    const devices = graph.nodes.filter((node) => node.kind === "device");
    return (
      <ul aria-label={t("graph.title")}>
        {devices.map((device) => (
          <li key={device.id}>
            <NodeDetails node={device} />
            <ul>
              {graph.edges
                .filter((edge) => edge.source === device.id && edge.target.startsWith("sensor:"))
                .map((edge) => graph.nodes.find((node) => node.id === edge.target))
                .map((sensor) => sensor && <li key={sensor.id}>{sensor.label}</li>)}
            </ul>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div>
      <div style={{ height: 480 }} aria-label={t("graph.title")} role="figure">
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          nodesDraggable={false}
          nodesConnectable={false}
          fitView
          onNodeClick={(_, node) => setSelected(graph.nodes.find((n) => n.id === node.id) ?? null)}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {selected ? <NodeDetails node={selected} /> : <p>{t("graph.hint")}</p>}
    </div>
  );
}

function NodeDetails({ node }: { node: GraphNode }) {
  const { t } = useI18n();
  return (
    <section aria-label={node.label}>
      <h4>{node.label}</h4>
      <dl>
        {node.details.map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {node.issues.length > 0 ? (
        <ul>
          {node.issues.map((issue) => (
            <li key={issue} className="issue">
              {issue}
            </li>
          ))}
        </ul>
      ) : (
        node.kind === "device" && <p>{t("graph.no_issue")}</p>
      )}
    </section>
  );
}
