// Réglages du calcul pour chaque équipement de la maison enregistrée (lot 3.1, phase 3) :
// comportement et prise en compte par le calcul ; batterie (lot 3.3) ; tarif (lot 3.2). Formulaires simples en attendant l'assistant
// de la phase 4, sur la même API (/api/configuration).

import { useEffect, useState } from "react";

import { ApiError, getJson, putJson } from "../api";
import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import {
  automationFor,
  BEHAVIORS,
  CONSTRAINED,
  isObserved,
  type Behavior,
  type Configuration,
  type ConfigurationIssue,
  type DeviceSettings,
  type TaskRules,
} from "./configuration";
import BatteryEditor from "./BatteryEditor";
import ConstraintEditor from "./ConstraintEditor";
import CycleEditor from "./CycleEditor";
import EnergyNeedEditor from "./EnergyNeedEditor";
import RuntimeEditor from "./RuntimeEditor";
import ObjectiveEditor from "./ObjectiveEditor";
import PanelsEditor from "./PanelsEditor";
import TariffEditor from "./TariffEditor";
import type { HomeDevice, HomeModel } from "./types";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; devices: HomeDevice[]; configuration: Configuration }
  | { status: "error" };

// Reprise des règles des tâches de HA : appliquées, aucune, HA absent, échec.
type RulesState = "idle" | "loading" | "applied" | "none" | "not_connected" | "failed";

type SaveState =
  | { status: "idle" | "saving" | "saved" | "failed" }
  | { status: "invalid"; issues: ConfigurationIssue[] };

// ``version`` change à chaque enregistrement de la maison : les réglages sont relus.
export default function ConfigurationSection({
  version,
  onNavigate,
}: {
  version: number;
  onNavigate: (target: string) => void;
}) {
  const { t } = useI18n();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  const [rules, setRules] = useState<RulesState>("idle");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<HomeModel>("api/home", controller.signal),
      getJson<Configuration>("api/configuration", controller.signal),
    ])
      .then(([home, configuration]) => setLoad({ status: "ready", devices: home.devices, configuration }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [version]);

  if (load.status === "loading") return <p>{t("configuration.loading")}</p>;
  if (load.status === "error") return <p role="alert">{t("configuration.error")}</p>;
  if (load.configuration.devices.length === 0) {
    return (
      <section aria-labelledby="configuration-title">
        <h2 id="configuration-title" className="visually-hidden">{t("configuration.title")}</h2>
        <p>{t("configuration.empty")}</p>
      </section>
    );
  }

  const { devices, configuration } = load;
  const byKey = new Map(devices.map((device) => [device.key, device]));
  // Batteries de la maison, vues comme une seule par le calcul ; null : pas de batterie.
  const batteries = devices.filter((device) => device.kind === "Battery");
  const batteryCapacity = batteries.length > 0 ? batteries.reduce((sum, d) => sum + (d.capacity_kwh ?? 0), 0) : null;
  // Première installation solaire : cible de la mise en route (« home#solar »).
  const firstSolar = configuration.devices.find((settings) => settings.behavior === "ProductionBehavior")?.key;

  const change = (key: string, update: Partial<DeviceSettings>) => {
    setSave({ status: "idle" });
    setLoad({
      ...load,
      configuration: {
        ...configuration,
        devices: configuration.devices.map((settings) =>
          settings.key === key ? { ...settings, ...update, default: false } : settings,
        ),
      },
    });
  };

  // Reprise des règles des descriptions JSON des tâches de HA (lot 3.5), à relire et enregistrer.
  const onImportRules = async () => {
    setRules("loading");
    try {
      const found = await getJson<TaskRules[]>("api/configuration/task-rules-proposal");
      const byDevice = new Map(found.map((r) => [r.key, r]));
      const applied = configuration.devices.filter((s) => byDevice.has(s.key) && s.behavior === "CycleBehavior");
      if (applied.length === 0) {
        setRules("none");
        return;
      }
      setSave({ status: "idle" });
      setLoad({
        ...load,
        configuration: {
          ...configuration,
          devices: configuration.devices.map((settings) => {
            const proposed = byDevice.get(settings.key);
            if (!proposed || settings.behavior !== "CycleBehavior") return settings;
            return {
              ...settings,
              recurrence: proposed.recurrence ?? settings.recurrence,
              after: proposed.after ?? settings.after,
              default: false,
            };
          }),
        },
      });
      setRules("applied");
    } catch (error) {
      setRules(error instanceof ApiError && error.status === 503 ? "not_connected" : "failed");
    }
  };

  const onSave = async () => {
    setSave({ status: "saving" });
    try {
      const saved = await putJson<Configuration>("api/configuration", configuration);
      setLoad({ ...load, configuration: saved });
      setSave({ status: "saved" });
    } catch (error) {
      if (error instanceof ApiError && error.status === 422 && Array.isArray(error.detail)) {
        setSave({ status: "invalid", issues: error.detail as ConfigurationIssue[] });
      } else {
        setSave({ status: "failed" });
      }
    }
  };

  return (
    <section aria-labelledby="configuration-title" className="expert-form">
      <h2 id="configuration-title" className="visually-hidden">{t("configuration.title")}</h2>
      <p>{t("configuration.intro")}</p>
      <p>
        <button type="button" onClick={() => void onImportRules()} disabled={rules === "loading"}>
          {t("configuration.import_rules")}
        </button>
      </p>
      {rules !== "idle" && rules !== "loading" && <p role="status">{t(`configuration.rules.${rules}`)}</p>}
      {configuration.devices.map((settings) => {
        const device = byKey.get(settings.key);
        const name = device?.name ?? settings.key;
        const choices = device ? BEHAVIORS[device.kind] : [settings.behavior];
        return (
          <article key={settings.key} id={`settings-${settings.key}`} aria-label={name} className="card expert-card">
            <h3>{name}</h3>
            <button type="button" className="link" onClick={() => onNavigate(`devices#device-${settings.key}`)}>
              {t("configuration.to_device")}
            </button>
            <label>
              {t("configuration.behavior")}{" "}
              <select
                value={settings.behavior}
                disabled={choices.length < 2}
                onChange={(event) => {
                  const behavior = event.target.value as Behavior;
                  change(settings.key, {
                    behavior,
                    automation: automationFor(behavior),
                    runtime: behavior === "RuntimeBehavior" ? settings.runtime : null,
                    energy: behavior === "EnergyByDeadlineBehavior" ? settings.energy : null,
                    constraints: CONSTRAINED.includes(behavior) ? settings.constraints : [],
                    after: behavior === "CycleBehavior" ? settings.after : null,
                    max_delay_days: behavior === "CycleBehavior" ? settings.max_delay_days : null,
                    recurrence: behavior === "CycleBehavior" ? settings.recurrence : null,
                  });
                }}
              >
                {choices.map((behavior) => (
                  <option key={behavior} value={behavior}>
                    {t(`behavior.${behavior}`)}
                  </option>
                ))}
              </select>
            </label>
            <Hint text={t(`configuration.behavior_hints.${settings.behavior}`)} />{" "}
            {!isObserved(settings.behavior) && (
              <label>
                <input
                  type="checkbox"
                  checked={settings.planned}
                  onChange={(event) => change(settings.key, { planned: event.target.checked })}
                />{" "}
                {t("configuration.planned")}
                <Hint text={t("configuration.planned_hint")} />
              </label>
            )}
            {settings.behavior === "ProductionBehavior" && (
              <div id={settings.key === firstSolar ? "solar" : undefined}>
                <PanelsEditor
                  panels={settings.panels ?? null}
                  name={name}
                  onChange={(panels) => change(settings.key, { panels })}
                />
              </div>
            )}
            {settings.behavior === "RuntimeBehavior" && settings.planned && (
              <RuntimeEditor
                runtime={settings.runtime ?? null}
                name={name}
                onChange={(runtime) => change(settings.key, { runtime })}
              />
            )}
            {settings.behavior === "EnergyByDeadlineBehavior" && settings.planned && (
              <EnergyNeedEditor
                need={settings.energy ?? null}
                name={name}
                onChange={(energy) => change(settings.key, { energy })}
              />
            )}
            {settings.behavior === "CycleBehavior" && settings.planned && (
              <CycleEditor
                after={settings.after ?? null}
                maxDelayDays={settings.max_delay_days ?? null}
                name={name}
                others={configuration.devices
                  .filter((other) => other.key !== settings.key && other.behavior === "CycleBehavior")
                  .map((other) => ({ key: other.key, name: byKey.get(other.key)?.name ?? other.key }))}
                recurrence={settings.recurrence ?? null}
                onChange={(cycle) => change(settings.key, cycle)}
              />
            )}
            {CONSTRAINED.includes(settings.behavior) && settings.planned && (
              <Advanced modified={(settings.constraints ?? []).length > 0}>
                <ConstraintEditor
                  constraints={settings.constraints ?? []}
                  name={name}
                  onChange={(constraints) => change(settings.key, { constraints })}
                />
              </Advanced>
            )}
            {settings.default && <p>{t("configuration.default")}</p>}
          </article>
        );
      })}
      {batteryCapacity !== null && (
        <div className="card expert-card">
          <h3 id="battery">{t("battery.title")}</h3>
          <BatteryEditor
            battery={configuration.battery ?? null}
            capacityKwh={batteryCapacity}
            onChange={(battery) => {
              setSave({ status: "idle" });
              setLoad({ ...load, configuration: { ...configuration, battery } });
            }}
          />
        </div>
      )}
      <div className="card expert-card">
        <h3 id="objective">{t("objective.title")}</h3>
        <ObjectiveEditor
          objective={configuration.objective ?? null}
          onChange={(objective) => {
            setSave({ status: "idle" });
            setLoad({ ...load, configuration: { ...configuration, objective } });
          }}
        />
      </div>
      <div className="card expert-card">
        <h3 id="tariff">{t("tariff.title")}</h3>
        <TariffEditor
          tariff={configuration.tariff ?? null}
          onChange={(tariff) => {
            setSave({ status: "idle" });
            setLoad({ ...load, configuration: { ...configuration, tariff } });
          }}
        />
      </div>
      <button type="button" onClick={() => void onSave()} disabled={save.status === "saving"}>
        {t("configuration.save")}
      </button>
      {save.status === "saved" && <p role="status">{t("configuration.saved")}</p>}
      {save.status === "failed" && <p role="alert">{t("configuration.save_failed")}</p>}
      {save.status === "invalid" && (
        <ul role="alert">
          {save.issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`} className="issue">
              {t(`configuration.issue.${issue.code}`, {
                ...issue.params,
                device: byKey.get(issue.device ?? "")?.name ?? issue.device ?? "",
              })}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
