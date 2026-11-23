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
  ControlButton,
  Controls,
  getViewportForBounds,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  useNodesInitialized,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
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

// Cadrage du dessin : centré dans la zone libre du canevas, entre le bas de la boîte de recherche
// et le bas du canevas, avec la même marge au-dessus et au-dessous. Le calcul est fait ici plutôt
// que par fitView : celui-ci centre sur toute la hauteur puis pousse le dessin juste sous la
// bande réservée — le dessin collait alors à la recherche (21 px) et laissait 46 px en bas.
// Le déplacement manuel, lui, peut passer sous la recherche ; seuls les recadrages l'évitent.
// Marges avec leur unité, rapportées à la zone libre : 8 % de chaque côté pour la vue entière,
// 12 % sur les résultats de la recherche (un peu plus d'air autour de quelques éléments).
const FIT_MARGIN = "8%" as const;
const SEARCH_MARGIN = "12%" as const;
// Bas de la recherche quand elle n'est pas encore affichée : 0,75 rem de marge et 2,75 rem de
// hauteur, comme dans styles.css.
const SEARCH_BOTTOM_PX = 56;
// Plancher de zoom assez bas pour que même une grande maison tienne entière dans la zone libre ;
// au-dessus de l'échelle 1, quelques éléments seraient grossis sans rien apporter.
const MIN_ZOOM = 0.02;
const MAX_ZOOM = 1;

type FlowInstance = ReturnType<typeof useReactFlow>;
type Margin = typeof FIT_MARGIN | typeof SEARCH_MARGIN;
// Élément à cadrer : son identifiant et sa position dans la vue.
type Placed = { id: string; position: { x: number; y: number } };

// Cadre les éléments donnés dans la zone libre du canevas. Les positions sont celles de la vue
// (après un double-clic, React Flow garde encore un instant les anciennes) ; les tailles, celles
// mesurées par React Flow, portées par ses éléments internes. Rien n'est fait — et `null` est
// rendu — tant que le canevas n'a pas de taille ou que ces éléments ne sont pas tous mesurés :
// l'appelant réessaie quand ils le sont.
function fitArea(
  instance: FlowInstance,
  canvas: HTMLElement | null,
  placed: readonly Placed[],
  { margin = FIT_MARGIN, duration = 0 }: { margin?: Margin; duration?: number } = {},
): Promise<boolean> | null {
  const flow = canvas?.querySelector<HTMLElement>(".react-flow");
  if (!flow || flow.clientWidth === 0 || flow.clientHeight === 0 || placed.length === 0) return null;
  const boxes: { x: number; y: number; width: number; height: number }[] = [];
  for (const { id, position } of placed) {
    const size = instance.getInternalNode(id)?.measured;
    if (!size?.width || !size?.height) return null;
    boxes.push({ ...position, width: size.width, height: size.height });
  }
  const left = Math.min(...boxes.map((box) => box.x));
  const top = Math.min(...boxes.map((box) => box.y));
  const bounds = {
    x: left,
    y: top,
    width: Math.max(...boxes.map((box) => box.x + box.width)) - left,
    height: Math.max(...boxes.map((box) => box.y + box.height)) - top,
  };
  const search = canvas?.querySelector(".graph-search");
  const band = search
    ? Math.max(0, search.getBoundingClientRect().bottom - flow.getBoundingClientRect().top)
    : SEARCH_BOTTOM_PX;
  const height = Math.max(1, flow.clientHeight - band);
  const viewport = getViewportForBounds(bounds, flow.clientWidth, height, MIN_ZOOM, MAX_ZOOM, margin);
  return instance.setViewport({ ...viewport, y: viewport.y + band }, { duration });
}

// Vue jamais cadrée : celle de départ de React Flow, coin haut gauche à l'échelle 1. Aucun
// cadrage réel n'y aboutit (le dessin entier ne tient jamais à l'échelle 1 calé dans le coin).
function untouched({ x, y, zoom }: { x: number; y: number; zoom: number }): boolean {
  return x === 0 && y === 0 && zoom === 1;
}

// Lance un cadrage dès que possible : tant que les éléments ne sont pas mesurés (ceux d'une
// nouvelle vue, ou mis à jour par une frappe dans la recherche, le sont à nouveau), nouvel essai
// à l'image suivante, pendant deux secondes au plus. Rend de quoi annuler les essais en attente.
function whenMeasured(run: () => Promise<boolean> | null, done?: (fit: Promise<boolean>) => void): () => void {
  let frame = 0;
  const attempt = (left: number) => {
    const fit = run();
    if (fit !== null) done?.(fit);
    else if (left > 0) frame = requestAnimationFrame(() => attempt(left - 1));
  };
  attempt(120);
  return () => cancelAnimationFrame(frame);
}

// Recadre le dessin à l'ouverture et à chaque changement de vue (double-clic, retour, plein
// écran) : la vue entière, dans la zone libre — exactement comme le bouton « centrer » des
// commandes, quel que soit l'élément. Le cadrage attend que les éléments de la vue soient
// mesurés ; celui de l'ouverture n'est pas animé, les suivants le sont.
// Filet : tant que la vue est restée celle de départ, le cadrage est refait, après chaque cadrage
// et à chaque changement de taille du canevas — une page ouverte sans être affichée (onglet ou
// panneau masqué, en cours de redimensionnement) laissait parfois le dessin non cadré, un coin
// seulement à l'échelle 1. Une vue déjà déplacée ou zoomée par l'utilisateur n'est jamais touchée.
// Les résultats de la recherche ne recadrent que quand le TEXTE de la recherche change :
// naviguer dans le graphe avec une recherche en cours ne décale plus rien — c'est ce qui
// décalait la sous-vue de certains éléments (ceux dont la vue contenait des correspondances).
export function Fitter({
  nodes,
  fullscreen,
  search,
  canvas,
}: {
  nodes: readonly Placed[];
  fullscreen: boolean;
  search: string;
  canvas: RefObject<HTMLElement | null>;
}) {
  const instance = useReactFlow();
  const initialized = useNodesInitialized();
  // Dernière vue reçue : la liste est refaite à chaque sélection ou frappe, sans que la vue change.
  // Tenue à jour avant les effets qui la lisent (ils passent après, dans l'ordre de déclaration).
  const latest = useRef(nodes);
  useLayoutEffect(() => {
    latest.current = nodes;
  }, [nodes]);
  const fitted = useRef<string | null>(null);
  const key = `${nodes.map((node) => node.id).join(" ")} ${String(fullscreen)}`;
  useEffect(() => {
    if (fitted.current === key) return;
    const first = fitted.current === null;
    return whenMeasured(
      () => fitArea(instance, canvas.current, latest.current, { duration: first ? 0 : 300 }),
      (fit) => {
        fitted.current = key;
        void fit.then(() => {
          if (untouched(instance.getViewport())) void fitArea(instance, canvas.current, latest.current);
        });
      },
    );
  }, [initialized, key, instance, canvas]);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      if (untouched(instance.getViewport())) void fitArea(instance, element, latest.current);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [canvas, instance]);
  // Le premier rendu n'a rien à recadrer de plus (l'effet au-dessus s'en charge) ; ensuite, seules
  // les frappes dans la recherche recadrent : sur les correspondances, ou la vue entière si la
  // recherche est vidée ou sans résultat — sans liste de nœuds vide, qui cadrerait sur rien.
  const typed = useRef(false);
  useEffect(() => {
    if (!typed.current) {
      typed.current = true;
      return;
    }
    const query = search.trim().toLowerCase();
    const labels = new Map(instance.getNodes().map((node) => [node.id, String(node.data.label).toLowerCase()]));
    const found = query ? latest.current.filter((node) => labels.get(node.id)?.includes(query)) : [];
    return whenMeasured(() =>
      fitArea(
        instance,
        canvas.current,
        found.length > 0 ? found : latest.current,
        found.length > 0 ? { margin: SEARCH_MARGIN, duration: 300 } : { duration: 300 },
      ),
    );
  }, [search, instance, canvas]);
  return null;
}

// Bouton « centrer » des commandes : même cadrage que l'ouverture (celui de React Flow centrerait
// sur toute la hauteur du canevas). Icône reprise du bouton d'origine.
function FitButton({ canvas }: { canvas: RefObject<HTMLElement | null> }) {
  const { t } = useI18n();
  const instance = useReactFlow();
  return (
    <ControlButton
      className="react-flow__controls-fitview"
      onClick={() => void fitArea(instance, canvas.current, instance.getNodes(), { duration: 300 })}
      title={t("graph.fit")}
      aria-label={t("graph.fit")}
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 30" aria-hidden="true">
        <path d="M3.692 4.63c0-.53.4-.938.939-.938h5.215V0H4.708C2.13 0 0 2.054 0 4.63v5.216h3.692V4.631zM27.354 0h-5.2v3.692h5.17c.53 0 .984.4.984.939v5.215H32V4.631A4.624 4.624 0 0027.354 0zm.954 24.83c0 .532-.4.94-.939.94h-5.215v3.768h5.215c2.577 0 4.631-2.13 4.631-4.707v-5.139h-3.692v5.139zm-23.677.94c-.531 0-.939-.4-.939-.94v-5.138H0v5.139c0 2.577 2.13 4.707 4.708 4.707h5.138V25.77H4.631z" />
      </svg>
    </ControlButton>
  );
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
  const canvasRef = useRef<HTMLDivElement>(null);

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
      ref={canvasRef}
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
          // Pas de fitView de React Flow : le cadrage, centré dans la zone libre, est fait par
          // Fitter (ouverture, changements de vue, recherche) et par le bouton « centrer ».
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
          <Fitter nodes={view.nodes} fullscreen={fullscreen} search={search} canvas={canvasRef} />
          <Background gap={28} />
          {/* Le bouton « centrer » des commandes recadre dans la zone libre, comme tous les
           * recadrages du dessin. */}
          <Controls showInteractive={false} showFitView={false}>
            <FitButton canvas={canvasRef} />
          </Controls>
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
