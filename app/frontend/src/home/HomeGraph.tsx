// Vue en graphe du modèle de la maison (lot 2t.3), en lecture seule : React Flow, chargé à la
// demande depuis l'onglet Maison. Toute l'ontologie est visible d'un coup, à la façon de
// l'aperçu de Microsoft Fabric : chaque type de la bibliothèque reçoit un secteur d'angle
// proportionnel à sa branche, étalée du centre vers l'extérieur (types propres, équipements,
// capteurs) ; les liaisons gardent leur sens et leur étiquette. Un clic ouvre la fiche de
// l'élément et met en avant ses liaisons. Sur un écran étroit (téléphone), une liste remplace
// le graphe.

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
import { buildGraph, type Graph, type GraphNode, type NodeKind } from "./graph";
import type { DeviceTypes, HomeModel } from "./types";

const NARROW = "(max-width: 700px)";

type Load = { status: "loading" } | { status: "ready"; graph: Graph } | { status: "error" };

function narrowScreen(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(NARROW).matches;
}

// Données portées par un nœud du dessin : le nom affiché, sa nature et ses anomalies.
type FlowNodeData = { label: string; kind: NodeKind; issues: number };
type FlowNode = Node<FlowNodeData, "home">;

// Poignées d'attache des liaisons, aux quatre côtés du nœud : sans elles, React Flow ne peut pas
// joindre les objets, et elles permettent de rattacher une flèche au côté qui fait face à son
// voisin, quelle que soit la disposition du dessin.
function HomeNode({ data }: NodeProps<FlowNode>) {
  const { t } = useI18n();
  return (
    <div className={`graph-node graph-${data.kind}`}>
      <Handle type="source" position={Position.Top} id="source-top" isConnectable={false} />
      <Handle type="target" position={Position.Top} id="target-top" isConnectable={false} />
      <Handle type="source" position={Position.Bottom} id="source-bottom" isConnectable={false} />
      <Handle type="target" position={Position.Bottom} id="target-bottom" isConnectable={false} />
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

// Profondeur de chaque nature d'objet, du centre du dessin vers l'extérieur.
const LEVELS: Record<NodeKind, number> = { library: 0, type: 1, device: 2, sensor: 3 };
const LEVEL_RADIUS = 420; // rayon du premier anneau, puis un pas par niveau
const RADIUS_STEP = 380;

// Branche d'un type de bibliothèque : ses types propres et équipements, puis leurs capteurs.
type Branch = { id: string; kind: NodeKind; children: Branch[]; leaves: number };

function branchTree(graph: Graph): Branch[] {
  const kinds = graph.edges.filter((edge) => edge.target.startsWith("kind:")).map((edge) => edge.target);
  const childrenOf = (id: string) => graph.edges.filter((edge) => edge.target === id).map((edge) => edge.source);
  const build = (id: string): Branch => {
    const node = graph.nodes.find((n) => n.id === id);
    const children = childrenOf(id).map(build);
    const leaves = children.length === 0 ? 1 : children.reduce((sum, child) => sum + child.leaves, 0);
    return { id, kind: node?.kind ?? "library", children, leaves };
  };
  return [...new Set(kinds)].map(build);
}

// Place une branche dans son secteur d'angle : la racine au milieu du secteur, ses enfants côte à
// côte, chacun avec une part du secteur proportionnelle à ses feuilles.
function placeBranch(
  branch: Branch,
  angleStart: number,
  angleEnd: number,
  positions: Map<string, { x: number; y: number }>,
) {
  const radius = LEVEL_RADIUS + LEVELS[branch.kind] * RADIUS_STEP;
  const middle = (angleStart + angleEnd) / 2;
  positions.set(branch.id, { x: Math.round(Math.cos(middle) * radius), y: Math.round(Math.sin(middle) * radius) });
  let cursor = angleStart;
  for (const child of branch.children) {
    const span = (angleEnd - angleStart) * (child.leaves / branch.leaves);
    placeBranch(child, cursor, cursor + span, positions);
    cursor += span;
  }
}

// Vue globale de l'ontologie : tous les objets du modèle, placés en anneaux autour du centre —
// un secteur par type de la bibliothèque, proportionnel à sa branche.
function layout(graph: Graph): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const branches = branchTree(graph);
  const total = branches.reduce((sum, branch) => sum + branch.leaves, 0);
  let cursor = -Math.PI / 2;
  for (const branch of branches) {
    const span = (2 * Math.PI * branch.leaves) / total;
    placeBranch(branch, cursor, cursor + span, positions);
    cursor += span;
  }
  // Objets sans branche (hors arbre) : dernier recours, au centre.
  for (const node of graph.nodes) {
    if (!positions.has(node.id)) positions.set(node.id, { x: 0, y: 0 });
  }
  return positions;
}

// Côté du nœud qui fait face à un point : la flèche entre deux objets s'attache au côté le plus
// direct, quelle que soit la position du voisin.
function sideFor(angle: number): "top" | "bottom" | "left" | "right" {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  if (cos >= Math.abs(sin)) return "right";
  if (-cos >= Math.abs(sin)) return "left";
  return sin >= 0 ? "bottom" : "top";
}

function handleToward(from: { x: number; y: number }, to: { x: number; y: number }): string {
  return sideFor(Math.atan2(to.y - from.y, to.x - from.x));
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

  // Échap ferme la fiche, comme le clic sur le fond du dessin.
  useEffect(() => {
    if (!selected) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selected]);

  // Toute l'ontologie d'un coup : les objets placés en anneaux, et les liaisons qui gardent leur
  // sens et leur étiquette ; celles de l'élément choisi sont mises en avant.
  const view = useMemo(() => {
    if (load.status !== "ready") return null;
    const positions = layout(load.graph);
    const nodes: FlowNode[] = load.graph.nodes.map(
      (node): FlowNode => ({
        id: node.id,
        type: "home",
        position: positions.get(node.id) ?? { x: 0, y: 0 },
        data: { label: node.label, kind: node.kind, issues: node.issues.length },
      }),
    );
    const edges: Edge[] = load.graph.edges.map((edge): Edge => {
      const linked = selected !== null && (edge.source === selected.id || edge.target === selected.id);
      const from = positions.get(edge.source) ?? { x: 0, y: 0 };
      const to = positions.get(edge.target) ?? { x: 0, y: 0 };
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: `source-${handleToward(from, to)}`,
        targetHandle: `target-${handleToward(to, from)}`,
        type: "default",
        label: edge.label,
        markerEnd: { type: MarkerType.ArrowClosed },
        animated: linked,
      };
    });
    return { nodes, edges };
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
        {view && (
          <ReactFlow
            nodes={view.nodes}
            edges={view.edges}
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
        )}
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
