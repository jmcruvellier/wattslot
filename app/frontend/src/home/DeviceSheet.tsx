// Fiche d'un appareil de « Ma maison » : ses réglages du calcul, puis, repliés, ses capteurs, son
// nom et son type, et le retrait de la maison. Un appareil proposé par Home Assistant mais pas
// encore suivi s'y ajoute. Un seul « Enregistrer » : la maison (/api/home) si son nom, son type ou
// ses capteurs changent, puis ses réglages (/api/configuration).

import { useState } from "react";

import { ApiError, putJson } from "../api";
import { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import Button from "../ui/Button";
import Sheet from "../ui/Sheet";
import { automationFor, BEHAVIORS, type Configuration, type ConfigurationIssue, type DeviceSettings as Settings } from "./configuration";
import DeviceSettings from "./DeviceSettings";
import { kindChoice, toModel, type DraftDevice } from "./draft";
import { ConfigurationIssues } from "./SettingsSheet";
import { DEVICE_KINDS, type DeviceKind, type DeviceType, type Issue } from "./types";

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
  onClose,
  onSaved,
}: {
  device: DraftDevice;
  home: DraftDevice[]; // toute la maison, pour l'enregistrer avec cet appareil modifié
  configuration: Configuration;
  types: DeviceType[];
  names: Map<string, string>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(device);
  const [settings, setSettings] = useState(() => configuration.devices.find((s) => s.key === device.key));
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  const included = device.included;
  const sensorIssues = draft.sensors.some((sensor) => sensor.issues.length > 0);

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
      <details className="expert-form home-fiche-details" open={!included || sensorIssues}>
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
            <input
              type="number"
              min="0"
              step="0.01"
              value={draft.capacityKwh ?? ""}
              onChange={(event) =>
                edit({ capacityKwh: event.target.value === "" ? null : Number(event.target.value) })
              }
            />
            {draft.capacitySource && <> {t("home.capacity_source", { entity: draft.capacitySource })}</>}
          </label>
        )}
        <ul>
          {draft.sensors.map((sensor, index) => (
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
              {t(`role.${sensor.role}`)} : <code>{sensor.entity_id}</code>
              {sensor.unit && ` (${sensor.unit})`}
              {sensor.resets_daily && ` — ${t("home.resets_daily")}`}
            </li>
          ))}
        </ul>
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
