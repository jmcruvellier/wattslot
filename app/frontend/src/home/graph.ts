// Graphe du modèle de la maison (lot 2t.3, designer en lecture seule) : types de la bibliothèque,
// types propres, équipements et capteurs, avec leurs liens. Fonction pure, indépendante de
// l'affichage : la vue (React Flow) et la liste (téléphone) en partent toutes deux.

import type { ConfigurationIssue } from "./configuration";
import type { DeviceType, HomeModel } from "./types";

export type NodeKind = "library" | "type" | "device" | "sensor";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  column: number; // 0 bibliothèque, 1 types propres, 2 équipements, 3 capteurs
  row: number;
  details: [string, string][]; // propriétés affichées au clic
  issues: string[]; // anomalies, déjà traduites
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

type Translate = (key: string, params?: Record<string, string | number>) => string;

// Espacement du dessin : assez large pour que les nœuds respirent et que les liens ne se
// croisent pas trop (la vue ajuste ensuite le zoom à la taille de l'écran).
export const COLUMN_WIDTH = 300;
export const ROW_HEIGHT = 90;

export function buildGraph(
  home: HomeModel,
  types: DeviceType[],
  issues: ConfigurationIssue[],
  t: Translate,
): Graph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const rows = [0, 0, 0, 0];
  const add = (node: Omit<GraphNode, "row">) => {
    nodes.push({ ...node, row: rows[node.column]++ });
  };

  const kinds = [...new Set([...home.devices.map((d) => d.kind), ...types.map((ty) => ty.parent)])];
  for (const kind of kinds) {
    add({ id: `kind:${kind}`, kind: "library", label: t(`kind.${kind}`), column: 0, details: [[t("graph.library"), kind]], issues: [] });
  }
  for (const own of types) {
    add({
      id: `type:${own.key}`,
      kind: "type",
      label: own.name,
      column: 1,
      details: [[t("graph.key"), own.key], [t("graph.parent"), t(`kind.${own.parent}`)]],
      issues: [],
    });
    edges.push({ id: `sub:${own.key}`, source: `type:${own.key}`, target: `kind:${own.parent}`, label: t("graph.subtype_of") });
  }
  for (const device of home.devices) {
    const id = `device:${device.key}`;
    const own = types.find((ty) => ty.key === device.custom_type);
    add({
      id,
      kind: "device",
      label: device.name,
      column: 2,
      details: [
        [t("graph.key"), device.key],
        [t("graph.type"), own ? own.name : t(`kind.${device.kind}`)],
        [t("graph.sensors"), String(device.sensors.length)],
        ...(device.capacity_kwh !== null ? [[t("graph.capacity"), `${device.capacity_kwh} kWh`] as [string, string]] : []),
      ],
      issues: issues
        .filter((issue) => issue.device === device.key)
        .map((issue) => t(`configuration.issue.${issue.code}`, { ...issue.params, device: device.name })),
    });
    edges.push({
      id: `is:${device.key}`,
      source: id,
      target: own ? `type:${own.key}` : `kind:${device.kind}`,
      label: t("graph.is_a"),
    });
    for (const sensor of device.sensors) {
      const sensorId = `sensor:${device.key}:${sensor.entity_id}`;
      add({
        id: sensorId,
        kind: "sensor",
        label: sensor.entity_id,
        column: 3,
        details: [[t("graph.role"), t(`role.${sensor.role}`)], [t("graph.entity"), sensor.entity_id]],
        issues: [],
      });
      edges.push({ id: `has:${sensorId}`, source: id, target: sensorId, label: t("graph.has_sensor") });
    }
  }
  return { nodes, edges };
}
