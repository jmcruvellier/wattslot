// Premier enregistrement de la maison (lot 2) : les équipements que l'application a reconnus
// dans le tableau Énergie de HA, tous retenus, à vérifier puis enregistrer d'un coup. Une fois la
// maison enregistrée, chaque appareil se règle dans sa fiche (onglet « Appareils »).

import { useCallback, useEffect, useState } from "react";

import { putJson } from "../api";
import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import AddDevice from "./AddDevice";
import { IssueList } from "./DeviceSheet";
import { kindChoice, loadHome, mergeDraft, toModel, type DraftDevice, type LoadResult } from "./draft";
import {
  DEVICE_KINDS,
  type DeviceType,
  type LibraryType,
  type HomeModel,
} from "./types";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; energyDashboard: boolean }
  | { status: "error"; code: "not_connected" | "failed" };

type SaveState = "idle" | "saving" | "saved" | "failed";

export default function HomeEditor({ onSaved }: { onSaved: () => void }) {
  const { t } = useI18n();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [draft, setDraft] = useState<DraftDevice[]>([]);
  const [save, setSave] = useState<SaveState>("idle");
  const [types, setTypes] = useState<DeviceType[]>([]);
  const [library, setLibrary] = useState<LibraryType[]>([]);

  const apply = useCallback((result: LoadResult, keepChoices: boolean) => {
    if (!result.ok) {
      setLoad({ status: "error", code: result.code });
      return;
    }
    setDraft((previous) => (keepChoices ? mergeDraft(previous, result.draft) : result.draft));
    setTypes(result.types);
    setLibrary(result.library);
    setLoad({ status: "ready", energyDashboard: result.energyDashboard });
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadHome(false).then((result) => {
      if (!cancelled) apply(result, false);
    });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  const onRefresh = async () => apply(await loadHome(true), true);

  const update = (key: string, change: Partial<DraftDevice>) => {
    setSave("idle");
    setDraft((devices) =>
      devices.map((device) => (device.key === key ? { ...device, ...change } : device)),
    );
  };

  const toggleSensor = (key: string, index: number, included: boolean) => {
    setSave("idle");
    setDraft((devices) =>
      devices.map((device) =>
        device.key === key
          ? {
              ...device,
              sensors: device.sensors.map((sensor, i) =>
                i === index ? { ...sensor, included } : sensor,
              ),
            }
          : device,
      ),
    );
  };

  const onSave = async () => {
    setSave("saving");
    try {
      await putJson<HomeModel>("api/home", toModel(draft));
      setSave("saved");
      onSaved();
    } catch {
      setSave("failed");
    }
  };

  if (load.status === "loading") return <p>{t("home.loading")}</p>;
  if (load.status === "error") return <p role="alert">{t(`home.error.${load.code}`)}</p>;
  if (!load.energyDashboard) return <p role="alert">{t("home.no_energy_dashboard")}</p>;

  const issueCount = draft.reduce(
    (count, device) =>
      count + device.issues.length + device.sensors.reduce((n, s) => n + s.issues.length, 0),
    0,
  );

  return (
    <section aria-labelledby="home-title" className="expert-form">
      <h2 className="visually-hidden" id="home-title">{t("home.title")}</h2>
      <p>{t("home.intro")}</p>
      {issueCount > 0 && <p role="status">{t("home.issue_count", { count: issueCount })}</p>}
      <button type="button" onClick={() => void onRefresh()}>
        {t("home.refresh")}
      </button>

      {draft.map((device) => (
        <article key={device.key} id={`device-${device.key}`} aria-label={device.name} className="card expert-card">
          <label>
            <input
              type="checkbox"
              checked={device.included}
              onChange={(event) => update(device.key, { included: event.target.checked })}
            />{" "}
            {t("home.include")}
          </label>
          <Hint text={t("home.include_hint")} />
          <label>
            {t("home.name")}{" "}
            <input
              value={device.name}
              onChange={(event) => update(device.key, { name: event.target.value })}
            />
          </label>
          <label>
            {t("home.kind")}{" "}
            <select
              value={device.customType ? `custom:${device.customType}` : device.kind}
              onChange={(event) => update(device.key, kindChoice(event.target.value, types))}
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
          {device.kind === "Battery" && (
            <label>
              {t("home.capacity")}{" "}
              <input
                type="number"
                min="0"
                step="0.01"
                value={device.capacityKwh ?? ""}
                onChange={(event) =>
                  update(device.key, {
                    capacityKwh: event.target.value === "" ? null : Number(event.target.value),
                  })
                }
              />
              {device.capacitySource && (
                <> {t("home.capacity_source", { entity: device.capacitySource })}</>
              )}
            </label>
          )}
          <IssueList issues={device.issues} />
          <p>{t("home.sensors_summary", { count: device.sensors.filter((sensor) => sensor.included).length })}</p>
          <Advanced modified={device.sensors.some((sensor) => !sensor.included || sensor.issues.length > 0)}>
          <ul>
            {device.sensors.map((sensor, index) => (
              <li key={`${sensor.role}-${sensor.entity_id}`}>
                <input
                  type="checkbox"
                  aria-label={t("home.keep_sensor", { entity: sensor.entity_id })}
                  checked={sensor.included}
                  onChange={(event) => toggleSensor(device.key, index, event.target.checked)}
                />{" "}
                {t(`role.${sensor.role}`)} : <code>{sensor.entity_id}</code>
                {sensor.unit && ` (${sensor.unit})`}
                {sensor.resets_daily && ` — ${t("home.resets_daily")}`}
                <IssueList issues={sensor.issues} />
              </li>
            ))}
          </ul>
          </Advanced>
        </article>
      ))}

      <div id="add-device">
      <AddDevice
        library={library}
        types={types}
        existing={draft.map((device) => device.key)}
        onAdd={(device) => {
          setSave("idle");
          setDraft((devices) => [...devices, device]);
        }}
      />
      </div>{" "}
      <button type="button" onClick={() => void onSave()} disabled={save === "saving"}>
        {t("home.save")}
      </button>
      {save === "saved" && <p role="status">{t("home.saved")}</p>}
      {save === "failed" && <p role="alert">{t("home.save_failed")}</p>}
    </section>
  );
}
