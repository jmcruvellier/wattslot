// Section « Notifications » des réglages (lot 5.6) : appareil commun et langue, puis pour chaque
// notification du catalogue l'activation, un appareil propre, des heures de silence et un essai ;
// la recommandation a aussi son rythme. Réglages de /api/settings/notifications, enregistrés
// avec le reste de la page.

import { useState } from "react";

import { putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { LANGUAGE_NAMES, LANGUAGES, type Language } from "../i18n/translate";

export type NotificationKind = "recommendation" | "device_now" | "plan_gap" | "battery_full" | "forecast_drop";
const KINDS: NotificationKind[] = ["recommendation", "device_now", "plan_gap", "battery_full", "forecast_drop"];

export interface QuietHours {
  start: string; // « 22:00:00 »
  end: string;
}

export interface Rule {
  enabled: boolean;
  service: string | null; // aucun : l'appareil commun
  quiet_hours: QuietHours | null;
}

export interface RecommendationRule extends Rule {
  cadence: "every_run" | "when_changed" | "daily";
  daily_at: string;
}

export interface NotificationSettings {
  service: string | null;
  language: Language;
  recommendation: RecommendationRule;
  device_now: Rule;
  plan_gap: Rule;
  battery_full: Rule;
  forecast_drop: Rule;
}

export interface Choice {
  id: string;
  name: string | null;
}

type Test = { status: "idle" | "sending" } | { status: "sent"; message: string } | { status: "failed"; reason: string };

const NOTIFY_PATTERN = /^notify\.[a-z0-9_]+$/;
const DEFAULT_QUIET: QuietHours = { start: "22:00", end: "07:00" };

/** « 22:00:00 » → « 22:00 » pour un champ d'heure. */
const hhmm = (value: string) => value.slice(0, 5);

function label(choice: Choice): string {
  return choice.name ? `${choice.name} (${choice.id})` : choice.id;
}

function ServiceSelect({
  id,
  value,
  choices,
  empty,
  onChange,
}: {
  id: string;
  value: string | null;
  choices: Choice[];
  empty: string;
  onChange: (value: string | null) => void;
}) {
  const { t } = useI18n();
  const known = value === null || choices.some((choice) => choice.id === value);
  return (
    <select id={id} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)}>
      <option value="">{empty}</option>
      {!known && <option value={value}>{t("settings.unknown", { id: value })}</option>}
      {choices.map((choice) => (
        <option key={choice.id} value={choice.id}>
          {label(choice)}
        </option>
      ))}
    </select>
  );
}

export default function NotificationSettingsSection({
  settings,
  choices,
  onChange,
}: {
  settings: NotificationSettings;
  choices: Choice[];
  onChange: (settings: NotificationSettings) => void;
}) {
  const { t } = useI18n();
  const [freeService, setFreeService] = useState("");
  const [tests, setTests] = useState<Partial<Record<NotificationKind, Test>>>({});

  const setRule = <K extends NotificationKind>(kind: K, patch: Partial<NotificationSettings[K]>) =>
    onChange({ ...settings, [kind]: { ...settings[kind], ...patch } });

  // L'essai envoie avec les réglages enregistrés : on enregistre d'abord.
  const onTest = async (kind: NotificationKind) => {
    setTests((current) => ({ ...current, [kind]: { status: "sending" } }));
    let result: Test;
    try {
      await putJson<NotificationSettings>("api/settings/notifications", settings);
      const response = await fetch(`api/notifications/${kind}/test`, { method: "POST" });
      const body = (await response.json().catch(() => ({}))) as { message?: string; detail?: unknown };
      if (response.ok) {
        result = { status: "sent", message: body.message ?? "" };
      } else {
        const known = ["no_notify_service", "no_plan"];
        const reason =
          response.status === 503
            ? "not_connected"
            : typeof body.detail === "string" && known.includes(body.detail)
              ? body.detail
              : "failed";
        result = { status: "failed", reason };
      }
    } catch {
      result = { status: "failed", reason: "failed" };
    }
    setTests((current) => ({ ...current, [kind]: result }));
  };

  return (
    <>
      <h3 id="notification">{t("settings.notification.title")}</h3>
      <p>{t("settings.notification.help")}</p>
      <label htmlFor="notify-service">{t("settings.notification.service")}</label>{" "}
      <ServiceSelect
        id="notify-service"
        value={settings.service}
        choices={choices}
        empty={t("settings.none")}
        onChange={(service) => onChange({ ...settings, service })}
      />
      <p>
        <label>
          {t("settings.notification.other")}{" "}
          <input
            value={freeService}
            placeholder="notify.mobile_app_…"
            onChange={(event) => setFreeService(event.target.value.trim())}
          />
        </label>{" "}
        <button
          type="button"
          disabled={!NOTIFY_PATTERN.test(freeService)}
          onClick={() => {
            onChange({ ...settings, service: freeService });
            setFreeService("");
          }}
        >
          {t("settings.notification.use")}
        </button>
      </p>
      <label>
        {t("settings.notification.language")}{" "}
        <select
          value={settings.language}
          onChange={(event) => onChange({ ...settings, language: event.target.value as Language })}
        >
          {LANGUAGES.map((code) => (
            <option key={code} value={code}>
              {LANGUAGE_NAMES[code]}
            </option>
          ))}
        </select>
      </label>

      {KINDS.map((kind) => {
        const rule = settings[kind];
        const test = tests[kind] ?? { status: "idle" };
        const service = rule.service ?? settings.service;
        const title = t(`settings.notification.kinds.${kind}.title`);
        return (
          <fieldset key={kind} className="notification-rule" aria-label={title}>
            <legend>
              <label>
                <input
                  type="checkbox"
                  checked={rule.enabled}
                  onChange={(event) => setRule(kind, { enabled: event.target.checked })}
                />{" "}
                {title}
              </label>
            </legend>
            <p className="dim">{t(`settings.notification.kinds.${kind}.help`)}</p>
            {kind === "recommendation" && (
              <p>
                <label>
                  {t("settings.notification.cadence.label")}{" "}
                  <select
                    value={settings.recommendation.cadence}
                    onChange={(event) =>
                      setRule("recommendation", { cadence: event.target.value as RecommendationRule["cadence"] })
                    }
                  >
                    <option value="every_run">{t("settings.notification.cadence.every_run")}</option>
                    <option value="when_changed">{t("settings.notification.cadence.when_changed")}</option>
                    <option value="daily">{t("settings.notification.cadence.daily")}</option>
                  </select>
                </label>{" "}
                {settings.recommendation.cadence === "daily" && (
                  <label>
                    {t("settings.notification.cadence.at")}{" "}
                    <input
                      type="time"
                      value={hhmm(settings.recommendation.daily_at)}
                      onChange={(event) => event.target.value && setRule("recommendation", { daily_at: event.target.value })}
                    />
                  </label>
                )}
              </p>
            )}
            <p>
              <label htmlFor={`notify-service-${kind}`}>{t("settings.notification.own_service")}</label>{" "}
              <ServiceSelect
                id={`notify-service-${kind}`}
                value={rule.service}
                choices={choices}
                empty={t("settings.notification.common_service")}
                onChange={(value) => setRule(kind, { service: value })}
              />
            </p>
            <p>
              <label>
                <input
                  type="checkbox"
                  checked={rule.quiet_hours !== null}
                  onChange={(event) => setRule(kind, { quiet_hours: event.target.checked ? DEFAULT_QUIET : null })}
                />{" "}
                {t("settings.notification.quiet.label")}
              </label>
              {rule.quiet_hours !== null && (
                <>
                  {" "}
                  <label>
                    {t("settings.notification.quiet.from")}{" "}
                    <input
                      type="time"
                      value={hhmm(rule.quiet_hours.start)}
                      onChange={(event) =>
                        event.target.value &&
                        setRule(kind, { quiet_hours: { ...rule.quiet_hours!, start: event.target.value } })
                      }
                    />
                  </label>{" "}
                  <label>
                    {t("settings.notification.quiet.to")}{" "}
                    <input
                      type="time"
                      value={hhmm(rule.quiet_hours.end)}
                      onChange={(event) =>
                        event.target.value &&
                        setRule(kind, { quiet_hours: { ...rule.quiet_hours!, end: event.target.value } })
                      }
                    />
                  </label>
                </>
              )}
            </p>
            <button
              type="button"
              disabled={service === null || test.status === "sending"}
              aria-label={t("settings.notification.test_of", { name: title })}
              onClick={() => void onTest(kind)}
            >
              {t(test.status === "sending" ? "settings.notification.sending" : "settings.notification.test")}
            </button>
            {test.status === "sent" && <p role="status">{t("settings.notification.sent", { message: test.message })}</p>}
            {test.status === "failed" && <p role="alert">{t(`settings.notification.failure.${test.reason}`)}</p>}
          </fieldset>
        );
      })}
    </>
  );
}
