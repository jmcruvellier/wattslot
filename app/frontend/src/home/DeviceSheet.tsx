// Fiche d'un appareil de « Ma maison » : ses réglages du calcul, puis, repliés, ses capteurs, son
// nom et son type, et le retrait de la maison. Un appareil proposé par Home Assistant mais pas
// encore suivi s'y ajoute. Chaque capteur se remplace par une liste des entités de HA dont
// l'unité convient à son rôle. Un seul « Enregistrer » : la maison (/api/home) si son nom, son
// type ou ses capteurs changent, puis ses réglages (/api/configuration).

import { useEffect, useState } from "react";

import { ApiError, getJson, putJson } from "../api";
import { Hint } from "../common/Advanced";
import NumberInput from "../common/NumberInput";
import { useI18n } from "../i18n/I18nProvider";
import Button from "../ui/Button";
import Sheet from "../ui/Sheet";
import { automationFor, BEHAVIORS, type Configuration, type ConfigurationIssue, type DeviceSettings as Settings } from "./configuration";
import DeviceSettings from "./DeviceSettings";
import { kindChoice, toModel, type DraftDevice, type DraftSensor } from "./draft";
import { ConfigurationIssues } from "./SettingsSheet";
import { DEVICE_KINDS, PHASES, type DeviceKind, type DeviceType, type EntityChoice, type Issue, type Phase } from "./types";

// Phases que mesure un capteur du réseau (pas « les trois phases » : c'est le total).
const LINES = PHASES.filter((phase) => phase !== "ThreePhases");

type SaveState =
  | { status: "idle" | "saving" | "failed" | "confirm_remove" }
  | { status: "invalid"; issues: ConfigurationIssue[] };

// Réglages ramenés au premier comportement du nouveau type quand l'ancien n'y est plus permis.
function forKind(settings: Settings, kind: DeviceKind): Settings {
  if (BEHAVIORS[kind].includes(settings.behavior)) return settings;
  const behavior = BEHAVIORS[kind][0];
  return {
    key: settings.key,
    behavior,
    automation: automationFor(behavior),
    planned: true,
    default: false,
  };
}

export default function DeviceSheet({
  device,
  home,
  configuration,
  types,
  names,
  threePhase = false,
  onClose,
  onSaved,
}: {
  device: DraftDevice;
  home: DraftDevice[]; // toute la maison, pour l'enregistrer avec cet appareil modifié
  configuration: Configuration;
  types: DeviceType[];
  names: Map<string, string>;
  threePhase?: boolean; // maison en triphasé : la fiche demande la phase de l'appareil
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(device);
  const [settings, setSettings] = useState(() => configuration.devices.find((s) => s.key === device.key));
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  const [choices, setChoices] = useState<EntityChoice[] | null>(null); // null : sans HA connecté
  const included = device.included;
  const sensorIssues = draft.sensors.some((sensor) => sensor.issues.length > 0);

  // Capteurs de HA qu'on peut lier, lus une fois ; sans HA connecté, le capteur actuel reste écrit.
  useEffect(() => {
    let cancelled = false;
    getJson<EntityChoice[]>("api/home/entities")
      .then((list) => !cancelled && setChoices(list))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const edit = (change: Partial<DraftDevice>) => {
    setSave({ status: "idle" });
    setDraft((current) => ({ ...current, ...change }));
  };

  const write = async (next: DraftDevice) => {
    setSave({ status: "saving" });
    const before = JSON.stringify(toModel(home));
    const model = toModel(home.map((d) => (d.key === next.key ? next : d)));
    try {
      if (JSON.stringify(model) !== before) await putJson("api/home", model);
      const saved = configuration.devices.find((s) => s.key === next.key);
      if (next.included && settings && saved && JSON.stringify(settings) !== JSON.stringify(saved)) {
        await putJson<Configuration>("api/configuration", {
          ...configuration,
          devices: configuration.devices.map((s) => (s.key === next.key ? settings : s)),
        });
      }
      onSaved();
    } catch (error) {
      if (error instanceof ApiError && error.status === 422 && Array.isArray(error.detail)) {
        setSave({ status: "invalid", issues: error.detail as ConfigurationIssue[] });
      } else {
        setSave({ status: "failed" });
      }
    }
  };

  const issues: Issue[] = [...draft.issues, ...draft.sensors.flatMap((sensor) => sensor.issues)];
  // Réseau en triphasé : chaque capteur mesure le total ou une seule phase.
  const byPhase = threePhase && draft.kind === "GridConnection";
  // Sa fiche s'ouvre sur ses capteurs tant qu'aucun ne mesure une phase : la mise en route y mène
  // pour les ajouter. Jugé à l'ouverture, pour ne pas la replier pendant la saisie.
  const [phaseMeters] = useState(byPhase && !device.sensors.some((sensor) => sensor.phase));
  const setSensor = (index: number, change: Partial<DraftSensor>) =>
    edit({ sensors: draft.sensors.map((s, i) => (i === index ? { ...s, ...change } : s)) });
  // Capteur par phase à ajouter : la première entité de HA qui convient et n'est pas déjà liée.
  const addPhaseSensor = (role: "EnergyImported" | "EnergyExported") => {
    const used = new Set(draft.sensors.filter((s) => s.role === role).map((s) => s.entity_id));
    const entity = (choices ?? []).find((e) => e.roles.includes(role) && !used.has(e.entity_id));
    if (!entity) return;
    const measured = new Set(draft.sensors.filter((s) => s.role === role).map((s) => s.phase));
    edit({
      sensors: [
        ...draft.sensors,
        {
          entity_id: entity.entity_id,
          role,
          name: entity.name,
          unit: entity.unit,
          resets_daily: entity.resets_daily,
          excluded: false,
          issues: [],
          included: true,
          phase: LINES.find((line) => !measured.has(line)) ?? "PhaseL1",
        },
      ],
    });
  };

  return (
    <Sheet open wide title={draft.name.trim() || device.name} onClose={onClose}>
      {issues.length > 0 && <IssueList issues={issues} />}
      {!included && <p>{t("home.fiche.proposed")}</p>}
      {included && settings && (
        <DeviceSettings
          settings={settings}
          kind={draft.kind}
          name={draft.name}
          others={configuration.devices
            .filter((other) => other.key !== device.key && other.behavior === "CycleBehavior")
            .map((other) => ({ key: other.key, name: names.get(other.key) ?? other.key }))}
          onChange={(update) => {
            setSave({ status: "idle" });
            setSettings({ ...settings, ...update, default: false });
          }}
        />
      )}
      {/* Maison en triphasé : la phase est demandée en clair, hors de la section repliée (la mise
          en route mène ici pour la régler). */}
      {threePhase && draft.kind !== "GridConnection" && (
        <div className="expert-form">
          <label>
            {t("home.phase")}{" "}
            <select
              value={draft.phase ?? ""}
              onChange={(event) => edit({ phase: (event.target.value || null) as Phase | null })}
            >
              <option value="">{t("home.phases.unknown")}</option>
              {PHASES.map((phase) => (
                <option key={phase} value={phase}>
                  {t(`home.phases.${phase}`)}
                </option>
              ))}
            </select>
          </label>
          <Hint text={t("home.phase_hint")} />
        </div>
      )}
      <details className="expert-form home-fiche-details" open={!included || sensorIssues || phaseMeters}>
        <summary>{t("home.fiche.details")}</summary>
        <label>
          {t("home.name")} <input value={draft.name} onChange={(event) => edit({ name: event.target.value })} />
        </label>
        <label>
          {t("home.kind")}{" "}
          <select
            value={draft.customType ? `custom:${draft.customType}` : draft.kind}
            onChange={(event) => {
              const choice = kindChoice(event.target.value, types);
              edit(choice);
              if (settings) setSettings(forKind(settings, choice.kind));
            }}
          >
            {DEVICE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {t(`kind.${kind}`)}
              </option>
            ))}
            {types.map((own) => (
              <option key={own.key} value={`custom:${own.key}`}>
                {t("home.custom_kind", { name: own.name, parent: t(`kind.${own.parent}`) })}
              </option>
            ))}
          </select>
        </label>
        <Hint text={t("home.kind_hint")} />
        {draft.kind === "Battery" && (
          <label>
            {t("home.capacity")}{" "}
            <NumberInput
              nullable
              min={0}
              step={0.01}
              value={draft.capacityKwh}
              onChange={(capacityKwh) => edit({ capacityKwh })}
            />
            {draft.capacitySource && <> {t("home.capacity_source", { entity: draft.capacitySource })}</>}
          </label>
        )}
        <ul>
          {draft.sensors.map((sensor, index) => {
            const candidates = (choices ?? []).filter((entity) => entity.roles.includes(sensor.role));
            return (
              <li key={`${sensor.role}-${sensor.entity_id}`}>
                <input
                  type="checkbox"
                  aria-label={t("home.keep_sensor", { entity: sensor.entity_id })}
                  checked={sensor.included}
                  onChange={(event) =>
                    edit({
                      sensors: draft.sensors.map((s, i) => (i === index ? { ...s, included: event.target.checked } : s)),
                    })
                  }
                />{" "}
                {t(`role.${sensor.role}`)} :{" "}
                <span className="home-fiche-sensor">
                  {choices ? (
                    <select
                      value={sensor.entity_id}
                      title={sensor.entity_id}
                      aria-label={t("home.change_sensor", { role: t(`role.${sensor.role}`) })}
                      onChange={(event) => {
                        const entity = choices.find((e) => e.entity_id === event.target.value);
                        if (!entity) return;
                        edit({
                          sensors: draft.sensors.map((s, i) =>
                            i === index
                              ? {
                                  ...s,
                                  entity_id: entity.entity_id,
                                  name: entity.name,
                                  unit: entity.unit,
                                  resets_daily: entity.resets_daily,
                                  excluded: false,
                                  issues: [],
                                }
                              : s,
                          ),
                        });
                      }}
                    >
                      {!candidates.some((entity) => entity.entity_id === sensor.entity_id) && (
                        <option value={sensor.entity_id}>{sensor.entity_id}</option>
                      )}
                      {candidates.map((entity) => (
                        <option key={entity.entity_id} value={entity.entity_id}>
                          {entity.name ? `${entity.name} (${entity.entity_id})` : entity.entity_id}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <code>{sensor.entity_id}</code>
                  )}
                  {sensor.unit && <span className="dim">({sensor.unit})</span>}
                </span>
                {byPhase && (sensor.role === "EnergyImported" || sensor.role === "EnergyExported") && (
                  <>
                    {" "}
                    <select
                      value={sensor.phase ?? ""}
                      aria-label={t("home.sensor_phase", { entity: sensor.entity_id })}
                      onChange={(event) => setSensor(index, { phase: (event.target.value || null) as Phase | null })}
                    >
                      <option value="">{t("home.sensor_phase_total")}</option>
                      {LINES.map((line) => (
                        <option key={line} value={line}>
                          {t(`home.phases.${line}`)}
                        </option>
                      ))}
                    </select>
                  </>
                )}
                {sensor.resets_daily && ` — ${t("home.resets_daily")}`}
              </li>
            );
          })}
        </ul>
        {byPhase && choices && (
          <p>
            <Button variant="quiet" onClick={() => addPhaseSensor("EnergyImported")}>
              {t("home.add_phase_import")}
            </Button>{" "}
            <Button variant="quiet" onClick={() => addPhaseSensor("EnergyExported")}>
              {t("home.add_phase_export")}
            </Button>
            <Hint text={t("home.sensor_phase_hint")} />
          </p>
        )}
        {included && (
          <p>
            <Button
              variant="quiet"
              onClick={() =>
                save.status === "confirm_remove"
                  ? void write({ ...draft, included: false })
                  : setSave({ status: "confirm_remove" })
              }
            >
              {t(save.status === "confirm_remove" ? "home.fiche.remove_confirm" : "home.fiche.remove")}
            </Button>
            {save.status === "confirm_remove" && <small>{t("home.fiche.remove_hint")}</small>}
          </p>
        )}
      </details>
      <div className="home-sheet-actions">
        {save.status === "failed" && <p role="alert">{t("home.save_failed")}</p>}
        {save.status === "invalid" && <ConfigurationIssues issues={save.issues} names={names} />}
        <Button
          variant="primary"
          onClick={() => void write({ ...draft, included: true })}
          disabled={save.status === "saving"}
        >
          {t(included ? "configuration.save" : "home.fiche.include")}
        </Button>
      </div>
    </Sheet>
  );
}

export function IssueList({ issues }: { issues: Issue[] }) {
  const { t } = useI18n();
  if (issues.length === 0) return null;
  return (
    <ul>
      {issues.map((issue, index) => (
        <li key={`${issue.code}-${index}`} className="issue">
          {t(`issue.${issue.code}`, issue.params)}
        </li>
      ))}
    </ul>
  );
}
