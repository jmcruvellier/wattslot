// Vue en graphe du modèle de la maison (lot 2t.3), en lecture seule : React Flow, chargé à la
// demande depuis l'onglet Maison, dans l'esprit d'un graphe d'ontologie — relations typées,
// fléchées et étiquetées, de la bibliothèque aux capteurs. Un clic sur un nœud ouvre une popup
// avec ses propriétés et ses anomalies, et met en avant ses liens. Sur un écran étroit
// (téléphone), une liste remplace le graphe.

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

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

// Poignées d'attache des liaisons : sans elles, React Flow ne peut pas joindre les objets. Celles
// de gauche relient un équipement à son type et au type de la bibliothèque (sens inverse), celles
// de droite relient un équipement à ses capteurs (sens direct).
function HomeNode({ data }: NodeProps<FlowNode>) {
  const { t } = useI18n();
  return (
    <div className={`graph-node graph-${data.kind}`}>
      <Handle type="source" position={Position.Left} id="source-left" isConnectable={false} />
      <Handle type="target" position={Position.Left} id="target-left" isConnectable={false} />
      <Handle type="source" position={Position.Right} id="source-right" isConnectable={false} />
      <Handle type="target" position={Position.Right} id="target-right" isConnectable={false} />
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

  // Liens d'ontologie : flèches et étiquettes de relation toujours visibles (« est un »,
  // « capteur »…), en escalier ; celles de l'élément sélectionné sont mises en avant. Les
  // relations de typage vont de droite à gauche (capteurs à droite, bibliothèque à gauche),
  // d'où le choix des poignées selon le sens du lien.
  const columns = useMemo(() => {
    if (load.status !== "ready") return new Map<string, number>();
    return new Map(load.graph.nodes.map((node) => [node.id, node.column]));
  }, [load]);

  const edges = useMemo<Edge[]>(() => {
    if (load.status !== "ready") return [];
    return load.graph.edges.map((edge): Edge => {
      const backward = (columns.get(edge.target) ?? 0) < (columns.get(edge.source) ?? 0);
      const linked = selected !== null && (edge.source === selected.id || edge.target === selected.id);
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: backward ? "source-left" : "source-right",
        targetHandle: backward ? "target-right" : "target-left",
        type: "smoothstep",
        label: edge.label,
        markerEnd: { type: MarkerType.ArrowClosed },
        animated: linked,
      };
    });
  }, [load, columns, selected]);

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
              <NodeDetails node={selected}>
                <button
                  type="button"
                  className="graph-details-close"
                  aria-label={t("graph.close")}
                  onClick={() => setSelected(null)}
                >
                  ✕
                </button>
              </NodeDetails>
            </Panel>
          )}
        </ReactFlow>
      </div>
    </div>
  );
}

// Fiche d'un élément : sa catégorie, son nom, ses propriétés puis ses anomalies. Rendue dans la
// popup du graphe (bouton de fermeture en enfant, en haut à droite) et dans la liste du téléphone.
function NodeDetails({ node, children }: { node: GraphNode; children?: ReactNode }) {
  const { t } = useI18n();
  return (
    <section className={`graph-details graph-${node.kind}`} aria-label={node.label}>
      {children}
      <p className="graph-details-kind">{t(`graph.node_${node.kind}`)}</p>
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
        node.kind === "device" && <p className="graph-details-ok">{t("graph.no_issue")}</p>
      )}
    </section>
  );
}
