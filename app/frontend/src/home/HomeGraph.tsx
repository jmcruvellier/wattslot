// Vue en graphe du modèle de la maison (lot 2t.3), en lecture seule : React Flow, chargé à la
// demande depuis l'onglet Maison. À la façon de l'explorateur d'ontologie de Microsoft Fabric :
// un élément au centre, ses voisins autour en cercle, reliés par des flèches étiquetées ; un clic
// sur un voisin le place au centre et ouvre sa fiche, et « Retour » revient à l'élément précédent.
// Sur un écran étroit (téléphone), une liste remplace le graphe.

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  useReactFlow,
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
// voisin, comme dans l'explorateur d'ontologie de Fabric.
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

// Côté du nœud qui fait face à un point : la flèche entre deux objets s'attache au côté le plus
// direct, quelle que soit la position du voisin dans le cercle.
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

// Recadre le dessin quand l'élément au centre change : le cercle des voisins grandit ou rétrécit.
function Fitter({ focus }: { focus: string | null }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    fitView({ padding: 0.2, maxZoom: 1 });
  }, [focus, fitView]);
  return null;
}

export default function HomeGraph() {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  // Élément au centre du dessin, fiche ouverte, et éléments déjà visités pour « Retour ».
  const [focus, setFocus] = useState<string | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [previous, setPrevious] = useState<string[]>([]);
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
        const graph = buildGraph(home, types.types, check.issues, t);
        setLoad({ status: "ready", graph });
        // À l'ouverture, le premier équipement est au centre et sa fiche est ouverte.
        const first = graph.nodes.find((node) => node.kind === "device") ?? graph.nodes[0];
        if (first) {
          setFocus((current) => current ?? first.id);
          setSelected((current) => current ?? first);
        }
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

  // Le dessin : l'élément au centre, ses voisins en cercle autour, et les liaisons qui les relient.
  const view = useMemo(() => {
    if (load.status !== "ready" || !focus) return null;
    const byId = new Map(load.graph.nodes.map((node) => [node.id, node]));
    const center = byId.get(focus);
    if (!center) return null;
    const links = load.graph.edges.filter((edge) => edge.source === focus || edge.target === focus);
    const neighborIds = [...new Set(links.flatMap((edge) => [edge.source, edge.target]))].filter((id) => id !== focus);
    // Rayon du cercle : les voisins assez espacés pour que les étiquettes restent lisibles.
    const radius = Math.max(360, neighborIds.length * 48);
    const neighbors = neighborIds.map((id, index): FlowNode => {
      const neighbor = byId.get(id)!;
      const angle = (2 * Math.PI * index) / neighborIds.length - Math.PI / 2;
      return {
        id,
        type: "home",
        position: { x: Math.round(Math.cos(angle) * radius), y: Math.round(Math.sin(angle) * radius) },
        data: { label: neighbor.label, kind: neighbor.kind, issues: neighbor.issues.length },
      };
    });
    const centerNode: FlowNode = {
      id: center.id,
      type: "home",
      className: "graph-focus",
      position: { x: 0, y: 0 },
      data: { label: center.label, kind: center.kind, issues: center.issues.length },
    };
    // Flèches étiquetées, du centre vers ses voisins : chaque extrémité s'attache au côté du nœud
    // qui fait face à l'autre, et la pointe garde le sens de la relation (l'équipement vers son
    // type, l'équipement vers son capteur).
    const edges: Edge[] = links.map((link): Edge => {
      const source = [centerNode, ...neighbors].find((node) => node.id === link.source)!;
      const target = [centerNode, ...neighbors].find((node) => node.id === link.target)!;
      return {
        id: link.id,
        source: link.source,
        target: link.target,
        sourceHandle: `source-${handleToward(source.position, target.position)}`,
        targetHandle: `target-${handleToward(target.position, source.position)}`,
        type: "default",
        label: link.label,
        markerEnd: { type: MarkerType.ArrowClosed },
      };
    });
    return { center, nodes: [centerNode, ...neighbors], edges };
  }, [load, focus]);

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

  // Un clic sur un voisin le place au centre et ouvre sa fiche ; un clic sur l'élément au centre
  // rouvre sa fiche ; « Retour » revient à l'élément précédent.
  const explore = (id: string) => {
    const node = graph.nodes.find((n) => n.id === id);
    if (!node) return;
    if (id === focus) {
      setSelected(node);
      return;
    }
    if (focus) setPrevious((path) => [...path, focus]);
    setFocus(id);
    setSelected(node);
  };

  const back = () => {
    const last = previous[previous.length - 1];
    if (!last) return;
    setPrevious((path) => path.slice(0, -1));
    setFocus(last);
    setSelected(graph.nodes.find((node) => node.id === last) ?? null);
  };

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
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            minZoom={0.1}
            onNodeClick={(_, node) => explore(node.id)}
            onPaneClick={() => setSelected(null)}
          >
            <Fitter focus={focus} />
            <Background gap={28} />
            <Controls showInteractive={false} />
            {previous.length > 0 && (
              <Panel position="top-left" className="graph-panel graph-panel-back">
                <button type="button" className="graph-back" onClick={back}>
                  ← {t("graph.back")}
                </button>
              </Panel>
            )}
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
