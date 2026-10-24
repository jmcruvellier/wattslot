// Vue en graphe du modèle de la maison (lot 2t.3), en lecture seule : React Flow, chargé à la
// demande depuis l'onglet Maison. Un clic sur un nœud ouvre une popup avec ses propriétés et ses
// anomalies, et met en avant ses liens ; les étiquettes des liens n'apparaissent qu'alors, pour
// ne pas surcharger le dessin. Sur un écran étroit (téléphone), une liste remplace le graphe.

import "@xyflow/react/dist/style.css";

import { Background, Controls, Panel, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";

import { getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import type { Configuration, ConfigurationIssue } from "./configuration";
import { buildGraph, COLUMN_WIDTH, type Graph, type GraphNode, type NodeKind, ROW_HEIGHT } from "./graph";
import type { DeviceTypes, HomeModel } from "./types";

const NARROW = "(max-width: 700px)";

type Load = { status: "loading" } | { status: "ready"; graph: Graph } | { status: "error" };

function narrowScreen(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(NARROW).matches;
}

// Données portées par un nœud du dessin : le nom affiché, sa colonne et ses anomalies.
type FlowNodeData = { label: string; kind: NodeKind; issues: number };
type FlowNode = Node<FlowNodeData, "home">;

// Nœud du dessin : une pastille de catégorie, le nom, et l'avertissement s'il y a des anomalies.
// L'apparence (thème clair ou sombre) vient des classes graph-node du fichier de styles.
function HomeNode({ data }: NodeProps<FlowNode>) {
  const { t } = useI18n();
  return (
    <div className={`graph-node graph-${data.kind}`}>
      <p className="graph-node-kind">{t(`graph.node_${data.kind}`)}</p>
      <p className="graph-node-label">
        {data.label}
        {data.issues > 0 && (
          <span className="graph-node-issue" title={t("graph.has_issue")} aria-hidden="true">
            ⚠
          </span>
        )}
      </p>
    </div>
  );
}

const NODE_TYPES = { home: HomeNode };

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

  // Échap ferme la popup des propriétés, comme le clic sur le fond du dessin.
  useEffect(() => {
    if (!selected) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selected]);

  const nodes = useMemo<FlowNode[]>(() => {
    if (load.status !== "ready") return [];
    return load.graph.nodes.map(
      (node): FlowNode => ({
        id: node.id,
        type: "home",
        position: { x: node.column * COLUMN_WIDTH, y: node.row * ROW_HEIGHT },
        data: { label: node.label, kind: node.kind, issues: node.issues.length },
      }),
    );
  }, [load]);

  // Les liens suivent le thème ; leurs étiquettes (« est un », « capteur »…) n'apparaissent que
  // pour l'élément sélectionné, sinon elles se croisent et rendent le dessin illisible.
  const edges = useMemo<Edge[]>(() => {
    if (load.status !== "ready") return [];
    return load.graph.edges.map((edge): Edge => {
      const linked = selected !== null && (edge.source === selected.id || edge.target === selected.id);
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "smoothstep",
        label: linked ? edge.label : undefined,
        animated: linked,
      };
    });
  }, [load, selected]);

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
    <div className="graph-view">
      <p className="graph-hint">{t("graph.hint")}</p>
      <div className="graph-canvas" role="figure" aria-label={t("graph.title")}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          nodesDraggable={false}
          nodesConnectable={false}
          fitView
          fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
          minZoom={0.1}
          onNodeClick={(_, node) => setSelected(graph.nodes.find((n) => n.id === node.id) ?? null)}
          onPaneClick={() => setSelected(null)}
        >
          <Background gap={28} />
          <Controls showInteractive={false} />
          {selected && (
            <Panel position="top-right" className="graph-panel">
              <div className="graph-details">
                <button type="button" className="graph-details-close" aria-label={t("graph.close")} onClick={() => setSelected(null)}>
                  ✕
                </button>
                <NodeDetails node={selected} />
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>
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
