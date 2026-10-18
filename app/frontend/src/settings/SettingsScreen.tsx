// Réglages de fonctionnement (lot 4.2) : liste de tâches, prévision de repli et calcul
// automatique (/api/settings/planning) ; notifications (lot 5.6, /api/settings/notifications) ;
// thème, gardé sur l'appareil (lot 6b.1). Lot 6b.6 : la page Réglages est une liste
// (`SettingsHome`) ; notifications, calcul et affichage ont chacun leur sous-page, et chaque
// sous-page enregistre ses propres réglages.
// Les choix sont lus dans HA (/api/settings/choices) ; sans HA, ou pour une valeur absente de la
// liste, la saisie libre reste possible.

import { useEffect, useState } from "react";

import { ApiError, getJson, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import AppearanceSection from "./AppearanceSection";
import SettingsHome from "./SettingsHome";
import NotificationSettingsSection, { type NotificationSettings } from "./NotificationSettings";
import StateMessage from "../ui/StateMessage";

export interface PlanningSettings {
  objective: string; // ancien réglage, gardé tel quel (l'objectif se règle dans Ma maison)
  todo_entity: string | null;
  forecast_entities: string[];
  scheduler_enabled: boolean;
  run_minute: number;
  // Réglages d'avant le lot 5.6, gardés tels quels : les notifications ont leurs réglages.
  notify_service: string | null;
  notify_language: string;
}

export interface Choice {
  id: string;
  name: string | null;
}

export interface SettingsChoices {
  connected: boolean;
  todo_lists: Choice[];
  notify_services: Choice[];
  forecast_entities: Choice[];
}

interface SchedulerStatus {
  enabled: boolean;
  next_run_at: string | null;
}

type Load =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      settings: PlanningSettings;
      notifications: NotificationSettings;
      choices: SettingsChoices;
      scheduler: SchedulerStatus | null;
    };

type Save = "idle" | "saving" | "saved" | "invalid" | "failed";
function label(choice: Choice): string {
  return choice.name ? `${choice.name} (${choice.id})` : choice.id;
}

// Liste déroulante des choix de HA, « aucun » compris, et la valeur actuelle si HA ne la propose
// pas (entité supprimée, HA déconnecté).
function ChoiceSelect({
  id,
  value,
  choices,
  onChange,
}: {
  id: string;
  value: string | null;
  choices: Choice[];
  onChange: (value: string | null) => void;
}) {
  const { t } = useI18n();
  const known = value === null || choices.some((choice) => choice.id === value);
  return (
    <select id={id} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)}>
      <option value="">{t("settings.none")}</option>
      {!known && <option value={value}>{t("settings.unknown", { id: value })}</option>}
      {choices.map((choice) => (
        <option key={choice.id} value={choice.id}>
          {label(choice)}
        </option>
      ))}
    </select>
  );
}

export type SettingsPage = "main" | "notifications" | "calculation" | "display";

export default function SettingsScreen({ page = "main" }: { page?: SettingsPage }) {
  const { t } = useI18n();
  if (page === "main") return <SettingsHome />;
  if (page === "display") {
    return (
      <section aria-labelledby="display-title">
        <h2 id="display-title" className="visually-hidden">
          {t("settings.appearance.title")}
        </h2>
        <AppearanceSection />
      </section>
    );
  }
  return <SettingsForm page={page} />;
}

function SettingsForm({ page }: { page: "notifications" | "calculation" }) {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [save, setSave] = useState<Save>("idle");
  const [attempt, setAttempt] = useState(0); // « Réessayer »

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<PlanningSettings>("api/settings/planning", controller.signal),
      getJson<NotificationSettings>("api/settings/notifications", controller.signal),
      getJson<SettingsChoices>("api/settings/choices", controller.signal),
      getJson<SchedulerStatus>("api/planning/status", controller.signal).catch(() => null),
    ])
      .then(([settings, notifications, choices, scheduler]) =>
        setLoad({ status: "ready", settings, notifications, choices, scheduler }),
      )
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [attempt]);

  if (load.status === "loading") return <StateMessage kind="loading" title={t("settings.loading")} />;
  if (load.status === "error") {
    return (
      <StateMessage
        kind="error"
        title={t("settings.error")}
        onRetry={() => {
          setLoad({ status: "loading" });
          setAttempt((count) => count + 1);
        }}
      />
    );
  }
  const { settings, notifications, choices, scheduler } = load;

  const change = (patch: Partial<PlanningSettings>) => {
    setSave("idle");
    setLoad({ ...load, settings: { ...settings, ...patch } });
  };

  const changeNotifications = (next: NotificationSettings) => {
    setSave("idle");
    setLoad({ ...load, notifications: next });
  };

  const onSave = async () => {
    setSave("saving");
    try {
      // Chaque sous-page enregistre ses propres réglages.
      if (page === "notifications") {
        const saved = await putJson<NotificationSettings>("api/settings/notifications", notifications);
        setLoad({ ...load, notifications: saved });
      } else {
        const saved = await putJson<PlanningSettings>("api/settings/planning", settings);
        setLoad({ ...load, settings: saved });
      }
      setSave("saved");
    } catch (error) {
      setSave(error instanceof ApiError && error.status === 422 ? "invalid" : "failed");
    }
  };

  const forecastChoices = [
    ...choices.forecast_entities,
    ...settings.forecast_entities
      .filter((id) => !choices.forecast_entities.some((choice) => choice.id === id))
      .map((id) => ({ id, name: null })),
  ];

  return (
    <section aria-labelledby="settings-page-title">
      {/* Titre de la barre du haut, repris pour l'ordre des titres de la page. */}
      <h2 id="settings-page-title" className="visually-hidden">
        {t(page === "notifications" ? "nav.notifications" : "nav.calculation")}
      </h2>
      {!choices.connected && <p role="status">{t("settings.not_connected")}</p>}
      {page === "calculation" && <p>{t("settings.intro")}</p>}

      {page === "notifications" && (
        <NotificationSettingsSection
          settings={notifications}
          choices={choices.notify_services}
          onChange={changeNotifications}
        />
      )}
      {page === "calculation" && (
        <>
      <h3 id="tasks">{t("settings.tasks.title")}</h3>
      <p>{t("settings.tasks.help")}</p>
      <label htmlFor="todo-entity">{t("settings.tasks.list")}</label>{" "}
      <ChoiceSelect
        id="todo-entity"
        value={settings.todo_entity}
        choices={choices.todo_lists}
        onChange={(todo_entity) => change({ todo_entity })}
      />


      <h3 id="forecast">{t("settings.forecast.title")}</h3>
      <p>{t("settings.forecast.help")}</p>
      {forecastChoices.length === 0 ? (
        <p>{t("settings.forecast.none")}</p>
      ) : (
        <fieldset>
          <legend>{t("settings.forecast.entities")}</legend>
          {forecastChoices.map((choice) => (
            <label key={choice.id}>
              <input
                type="checkbox"
                checked={settings.forecast_entities.includes(choice.id)}
                onChange={(event) =>
                  change({
                    forecast_entities: event.target.checked
                      ? [...settings.forecast_entities, choice.id]
                      : settings.forecast_entities.filter((id) => id !== choice.id),
                  })
                }
              />{" "}
              {label(choice)}
            </label>
          ))}
        </fieldset>
      )}

      <h3 id="scheduler">{t("settings.scheduler.title")}</h3>
      <label>
        <input
          type="checkbox"
          checked={settings.scheduler_enabled}
          onChange={(event) => change({ scheduler_enabled: event.target.checked })}
        />{" "}
        {t("settings.scheduler.enabled")}
      </label>{" "}
      <label>
        {t("settings.scheduler.minute")}{" "}
        <input
          type="number"
          min={0}
          max={59}
          value={settings.run_minute}
          disabled={!settings.scheduler_enabled}
          onChange={(event) => {
            const minute = Math.round(Number(event.target.value));
            if (Number.isFinite(minute)) change({ run_minute: Math.min(59, Math.max(0, minute)) });
          }}
        />
      </label>
      {scheduler?.enabled && scheduler.next_run_at && (
        <p>{t("settings.scheduler.next", { time: new Date(scheduler.next_run_at).toLocaleString() })}</p>
      )}


        </>
      )}

      <p>
        <button type="button" disabled={save === "saving"} onClick={() => void onSave()}>
          {t("settings.save")}
        </button>
      </p>
      {save === "saved" && <p role="status">{t("settings.saved")}</p>}
      {(save === "invalid" || save === "failed") && <p role="alert">{t(`settings.${save}`)}</p>}
    </section>
  );
}
