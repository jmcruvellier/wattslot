// Vue en graphe du modèle de la maison (lot 2t.3), en lecture seule : React Flow, chargé à la
// demande depuis l'onglet Maison. Toute l'ontologie est visible d'un coup, à la façon de
// l'aperçu de Microsoft Fabric : chaque type de la bibliothèque reçoit un secteur d'angle
// proportionnel à sa branche, étalée du centre vers l'extérieur (types propres, équipements,
// capteurs). Un clic ouvre la fiche de l'élément et met en avant ses liaisons ; un double-clic
// entre dans l'élément — lui au centre, ses voisins autour. Le canevas passe en plein écran
// (Échap ou ✕ pour sortir) et une recherche met en évidence les éléments correspondants, en
// recadrant le dessin sur eux. Sur un écran étroit (téléphone), une liste remplace le graphe.

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
import { createPortal } from "react-dom";

import { getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import type { Configuration, ConfigurationIssue } from "./configuration";
import { buildGraph, type Graph, type GraphNode, type NodeKind } from "./graph";
import { layout, layoutInside } from "./layout";
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

// Hauteur réservée en haut du canevas pour la boîte de recherche (et son message « Aucun
// résultat ») : le dessin recadré ne passe jamais dessous. Le déplacement manuel, lui, peut
// y passer — seule l'ouverture et les recadrages évitent la bande.
const SEARCH_BAND = "76px" as const;

// Recadrage avec la bande de recherche réservée en haut : à l'ouverture de la vue, par le bouton
// « centrer » des commandes (sous les boutons de zoom), et à chaque changement de vue ou sur les
// résultats de la recherche.
const FIT_MARGIN = 0.2;
// Plancher de zoom assez bas pour que même une grande maison tienne entière dans le canevas
// avec sa bande : sinon le cadrage est écrêté, la bande n'est plus respectée et le bas du
// dessin disparaît.
const MIN_ZOOM = 0.02;
const FIT_OPTIONS = {
  padding: { top: SEARCH_BAND, right: FIT_MARGIN, bottom: FIT_MARGIN, left: FIT_MARGIN },
  minZoom: MIN_ZOOM,
  maxZoom: 1,
};

// Recadre le dessin au changement de vue (l'ensemble est plus large que l'intérieur d'un
// élément), au passage en plein écran et sur les résultats de la recherche.
function Fitter({ zoomed, fullscreen, hits }: { zoomed: string | null; fullscreen: boolean; hits: string }) {
  const instance = useReactFlow();
  useEffect(() => {
    const ids = hits ? hits.split(",") : [];
    if (ids.length > 0) {
      // Résultats de la recherche : cadrés plus près, toujours sous la bande.
      instance.fitView({
        ...FIT_OPTIONS,
        nodes: ids.map((id) => ({ id })),
        padding: { top: SEARCH_BAND, right: 0.3, bottom: 0.3, left: 0.3 },
        duration: 300,
      });
    } else {
      instance.fitView({ ...FIT_OPTIONS, duration: 300 });
    }
  }, [zoomed, fullscreen, hits, instance]);
  return null;
}

export default function HomeGraph() {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [selected, setSelected] = useState<GraphNode | null>(null);
  // Élément zoomé par un double-clic (vue de l'intérieur), null pour la vue d'ensemble.
  const [zoomed, setZoomed] = useState<string | null>(null);
  // Canevas plein écran (par-dessus toute l'application) et texte de la recherche courante.
  const [fullscreen, setFullscreen] = useState(false);
  const [search, setSearch] = useState("");
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

  // Échap referme d'abord la fiche ouverte, puis quitte le plein écran ; ignoré dans le champ de
  // recherche (Échap y efface le texte, comme d'habitude dans un champ).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if ((event.target as HTMLElement)?.closest?.(".graph-search")) return;
      if (selected) setSelected(null);
      else if (fullscreen) setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selected, fullscreen]);

  // Le dessin : toute l'ontologie d'un coup (anneaux autour du centre), ou l'intérieur d'un
  // élément double-cliqué (lui au centre, ses voisins autour). Les liaisons gardent leur sens et
  // leur étiquette ; celles de l'élément choisi (fiche ouverte) sont mises en avant. La recherche
  // s'applique à la vue courante : les éléments trouvés ressortent, le reste s'efface.
  const view = useMemo(() => {
    if (load.status !== "ready") return null;
    const inside = zoomed !== null ? layoutInside(load.graph, zoomed) : null;
    const positions = inside ? inside.positions : layout(load.graph);
    const ids = inside ? inside.ids : load.graph.nodes.map((node) => node.id);
    const query = search.trim().toLowerCase();
    const matched = query
      ? new Set(ids.filter((id) => (load.graph.nodes.find((n) => n.id === id)?.label ?? "").toLowerCase().includes(query)))
      : null;
    const nodes: FlowNode[] = ids.map((id): FlowNode => {
      const node = load.graph.nodes.find((n) => n.id === id)!;
      const classes = [id === zoomed ? "graph-focus" : undefined, matched ? (matched.has(id) ? "graph-hit" : "graph-dim") : undefined];
      return {
        id,
        type: "home",
        className: classes.filter(Boolean).join(" ") || undefined,
        position: positions.get(id) ?? { x: 0, y: 0 },
        data: { label: node.label, kind: node.kind, issues: node.issues.length },
      };
    });
    const edges: Edge[] = load.graph.edges
      .filter((edge) => inside === null || edge.source === zoomed || edge.target === zoomed)
      .map((edge): Edge => {
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
          className: matched && !(matched.has(edge.source) && matched.has(edge.target)) ? "graph-edge-dim" : undefined,
        };
      });
    return { nodes, edges, matched, ids };
  }, [load, selected, zoomed, search]);

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

  // Le canevas seul passe en plein écran : par-dessus toute l'application, il couvre la page
  // entière (portail vers le corps du document, pour échapper aux mises en page de l'onglet).
  const canvas = (
    <div
      className={fullscreen ? "graph-canvas graph-fullscreen" : "graph-canvas"}
      role="figure"
      aria-label={t("graph.title")}
    >
      {view && (
        <ReactFlow
          nodes={view.nodes}
          edges={view.edges}
          nodeTypes={NODE_TYPES}
          nodesDraggable={false}
          nodesConnectable={false}
          fitView
          fitViewOptions={FIT_OPTIONS}
          minZoom={MIN_ZOOM}
          onNodeClick={(_, node) => setSelected(graph.nodes.find((n) => n.id === node.id) ?? null)}
          // Double-clic : entre dans l'élément (lui au centre, ses voisins autour) et ouvre sa
          // fiche ; sur l'élément déjà au centre, ressort à la vue d'ensemble. Le zoom du
          // double-clic est coupé : il entrerait en conflit avec cette navigation.
          zoomOnDoubleClick={false}
          onNodeDoubleClick={(_, node) => {
            setZoomed((current) => (node.id === current ? null : node.id));
            setSelected(graph.nodes.find((n) => n.id === node.id) ?? null);
          }}
          onPaneClick={() => setSelected(null)}
        >
          <Fitter zoomed={zoomed} fullscreen={fullscreen} hits={view.matched ? [...view.matched].join(",") : ""} />
          <Background gap={28} />
          {/* Le bouton « centrer » des commandes recadre avec la bande de recherche réservée,
           * comme tous les recadrages du dessin. */}
          <Controls showInteractive={false} fitViewOptions={FIT_OPTIONS} />
          <Panel position="top-left" className="graph-panel graph-panel-tools">
            <div className="graph-tools">
              {zoomed && (
                <button type="button" className="graph-back" onClick={() => setZoomed(null)}>
                  ← {t("graph.back")}
                </button>
              )}
              <button
                type="button"
                className="graph-back"
                aria-label={fullscreen ? t("graph.fullscreen_exit") : t("graph.fullscreen")}
                title={fullscreen ? t("graph.fullscreen_exit") : t("graph.fullscreen")}
                onClick={() => setFullscreen((on) => !on)}
              >
                {fullscreen ? "✕" : "⤢"}
              </button>
            </div>
          </Panel>
          <Panel position="top-center" className="graph-panel graph-panel-search">
            <div className="graph-search">
              <input
                type="text"
                className="graph-search-input"
                placeholder={t("graph.search")}
                aria-label={t("graph.search")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {search && (
                <button
                  type="button"
                  className="graph-search-clear"
                  aria-label={t("graph.search_clear")}
                  onClick={() => setSearch("")}
                >
                  ✕
                </button>
              )}
              {view.matched && view.matched.size === 0 && (
                <p className="graph-search-none" role="status">
                  {t("graph.search_none")}
                </p>
              )}
            </div>
          </Panel>
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
  );

  return (
    <div className="graph-view">
      <p className="graph-hint">{t("graph.hint")}</p>
      {fullscreen ? createPortal(canvas, document.body) : canvas}
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
