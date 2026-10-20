// Brouillon du modèle de la maison : propositions de l'application, fusionnées avec ce que
// l'utilisateur a déjà validé, puis modifiées dans l'écran avant enregistrement.

import { ApiError, getJson } from "../api";
import type {
  DeviceKind,
  DeviceProposal,
  DeviceType,
  DeviceTypes,
  HomeDevice,
  HomeModel,
  HomeProposal,
  Issue,
  LibraryType,
  SensorProposal,
} from "./types";

export const MANUAL_PREFIX = "manual-"; // clé d'un équipement ajouté à la main (AddDevice)

/** Clé lisible tirée d'un nom : minuscules, sans accents, tirets. */
export function slug(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export interface DraftSensor extends SensorProposal {
  included: boolean;
}

export interface DraftDevice {
  key: string;
  included: boolean;
  kind: DeviceKind;
  customType: string | null; // type propre (lot 2t.1), sous-type de kind
  name: string;
  capacityKwh: number | null;
  capacitySource: string | null; // entité HA dont la capacité proposée a été lue
  sensors: DraftSensor[];
  issues: Issue[];
}

const sensorKey = (sensor: { entity_id: string; role: string }) =>
  `${sensor.role}|${sensor.entity_id}`;

/**
 * Capteurs d'un équipement : pour un équipement déjà validé, ceux qui ont été enregistrés ;
 * sinon, tous sauf ceux que l'application propose d'exclure (un coût déclaré comme compteur).
 */
function draftSensors(proposal: DeviceProposal, existing: HomeDevice | undefined): DraftSensor[] {
  const saved = existing ? new Set(existing.sensors.map(sensorKey)) : null;
  return proposal.sensors.map((sensor) => ({
    ...sensor,
    included: saved ? saved.has(sensorKey(sensor)) : !sensor.excluded,
  }));
}

/**
 * Sans modèle enregistré, toutes les propositions sont retenues. Sinon, seuls les équipements
 * déjà validés le sont, avec le nom, le type, la capacité et les capteurs choisis par
 * l'utilisateur ; les nouvelles propositions apparaissent décochées.
 */
export function buildDraft(proposals: DeviceProposal[], saved: HomeModel): DraftDevice[] {
  const savedByKey = new Map(saved.devices.map((device) => [device.key, device]));
  const firstValidation = saved.devices.length === 0;
  const draft: DraftDevice[] = proposals.map((proposal) => {
    const existing = savedByKey.get(proposal.key);
    return {
      key: proposal.key,
      included: firstValidation || existing !== undefined,
      kind: existing?.kind ?? proposal.kind,
      customType: existing?.custom_type ?? null,
      name: existing?.name ?? proposal.name,
      capacityKwh: existing?.capacity_kwh ?? proposal.capacity_kwh,
      capacitySource: proposal.capacity_source ?? null,
      sensors: draftSensors(proposal, existing),
      issues: proposal.issues,
    };
  });
  // Équipements validés qui ne sont plus proposés (retirés du tableau Énergie) : gardés.
  const proposed = new Set(proposals.map((proposal) => proposal.key));
  for (const device of saved.devices) {
    if (proposed.has(device.key)) continue;
    draft.push({
      key: device.key,
      included: true,
      kind: device.kind,
      customType: device.custom_type ?? null,
      name: device.name,
      capacityKwh: device.capacity_kwh,
      capacitySource: null,
      sensors: device.sensors.map((sensor) => ({
        ...sensor,
        name: null,
        unit: null,
        excluded: false,
        issues: [],
        included: true,
      })),
      // Ajouté à la main : jamais proposé, ce n'est pas une anomalie.
      issues: device.key.startsWith(MANUAL_PREFIX) ? [] : [{ code: "not_proposed", params: {} }],
    });
  }
  return draft;
}

/** Garde les choix en cours (coches, noms, types) quand les propositions sont relues. */
export function mergeDraft(previous: DraftDevice[], next: DraftDevice[]): DraftDevice[] {
  const byKey = new Map(previous.map((device) => [device.key, device]));
  return next.map((device) => {
    const old = byKey.get(device.key);
    if (!old) return device;
    const oldSensors = new Map(old.sensors.map((sensor) => [sensorKey(sensor), sensor.included]));
    return {
      ...device,
      included: old.included,
      kind: old.kind,
      customType: old.customType,
      name: old.name,
      capacityKwh: old.capacityKwh,
      sensors: device.sensors.map((sensor) => ({
        ...sensor,
        included: oldSensors.get(sensorKey(sensor)) ?? sensor.included,
      })),
    };
  });
}

export function toModel(draft: DraftDevice[]): HomeModel {
  return {
    devices: draft
      .filter((device) => device.included)
      .map((device) => ({
        key: device.key,
        kind: device.kind,
        custom_type: device.customType,
        name: device.name.trim() || device.key,
        capacity_kwh: device.kind === "Battery" ? device.capacityKwh : null,
        sensors: device.sensors
          .filter((sensor) => sensor.included)
          .map(({ entity_id, role, resets_daily }) => ({ entity_id, role, resets_daily })),
      })),
  };
}

// Choix du type : un type de la bibliothèque, ou un type propre (et alors son parent).
export function kindChoice(value: string, types: DeviceType[]): { kind: DeviceKind; customType: string | null } {
  const own = value.startsWith("custom:") ? types.find((t) => t.key === value.slice(7)) : undefined;
  return own ? { kind: own.parent, customType: own.key } : { kind: value as DeviceKind, customType: null };
}

// Propositions de HA fusionnées avec la maison enregistrée, et types d'appareils.
export type LoadResult =
  | { ok: true; draft: DraftDevice[]; energyDashboard: boolean; types: DeviceType[]; library: LibraryType[] }
  | { ok: false; code: "not_connected" | "failed" };

export async function loadHome(refresh: boolean): Promise<LoadResult> {
  try {
    const [proposal, saved, types] = await Promise.all([
      getJson<HomeProposal>(`api/home/proposals${refresh ? "?refresh=true" : ""}`),
      getJson<HomeModel>("api/home"),
      // Types propres : sans eux, l'écran reste utilisable avec ceux de la bibliothèque.
      getJson<DeviceTypes>("api/home/types").catch(() => ({ parents: [], types: [], library: [] })),
    ]);
    return {
      ok: true,
      draft: buildDraft(proposal.devices, saved),
      energyDashboard: proposal.energy_dashboard,
      types: types.types,
      library: types.library,
    };
  } catch (error) {
    const notConnected = error instanceof ApiError && error.status === 503;
    return { ok: false, code: notConnected ? "not_connected" : "failed" };
  }
}
