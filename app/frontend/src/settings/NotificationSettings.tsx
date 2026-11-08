// Section « Notifications » des réglages (lot 5.6), en listes comme les autres pages : l'envoi
// (appareil commun, autre service, langue), puis une ligne par notification du catalogue avec
// son interrupteur. Une notification activée montre ses options en résumé (rythme, appareil,
// heures de silence), qui se déplie pour les régler et envoyer un essai. Le planning de la semaine
// a ses jours d'envoi et son heure. Réglages de /api/settings/notifications, enregistrés avec le
// reste de la page.

import { useState } from "react";

import { putJson } from "../api";
import { useHomeFeatures } from "../home/features";
import { useI18n } from "../i18n/I18nProvider";
import { LANGUAGE_NAMES, LANGUAGES, type Language } from "../i18n/translate";
import Icon from "../ui/Icon";
import { SettingList } from "../ui/SettingRow";
import Switch from "../ui/Switch";

export type NotificationKind =
  | "recommendation"
  | "week"
  | "device_now"
  | "plan_gap"
  | "battery_full"
  | "forecast_drop"
  | "resources";
const KINDS: NotificationKind[] = ["recommendation", "week", "device_now", "plan_gap", "battery_full", "forecast_drop", "resources"];

// Jours de la semaine, lundi = 0 comme côté serveur ; libellés de l'éditeur de cycle.
const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"] as const;

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

export interface WeekRule extends Rule {
  weekdays: number[]; // lundi = 0
  at: string;
}

export interface NotificationSettings {
  service: string | null;
  language: Language;
  recommendation: RecommendationRule;
  week: WeekRule;
  device_now: Rule;
  plan_gap: Rule;
  battery_full: Rule;
  forecast_drop: Rule;
  resources: Rule; // alertes de ressources (disque, mémoire, calcul lent), activées par défaut
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

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** Nom d'un service dans les listes : son nom dans HA, sinon son identifiant. */
function label(choice: Choice): string {
  return choice.name ?? choice.id;
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
        <option key={choice.id} value={choice.id} title={choice.id}>
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
  const features = useHomeFeatures();
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
        const known = ["no_notify_service", "no_plan", "no_week"];
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

  // Résumé des options d'une notification : rythme, appareil, heures de silence.
  const summary = (kind: NotificationKind) => {
    const rule = settings[kind];
    const parts: string[] = [];
    if (kind === "recommendation") {
      const { cadence, daily_at } = settings.recommendation;
      parts.push(
        cadence === "daily"
          ? `${t("settings.notification.cadence.daily")} ${t("settings.notification.cadence.at")} ${hhmm(daily_at)}`
          : t(`settings.notification.cadence.${cadence}`),
      );
    }
    if (kind === "week") {
      const { weekdays, at } = settings.week;
      const days = [...weekdays].sort((a, b) => a - b).map((day) => t(`cycle.weekdays.${WEEKDAYS[day]}`));
      parts.push(`${days.join(", ")} ${t("settings.notification.cadence.at")} ${hhmm(at)}`);
    }
    const own = rule.service && choices.find((choice) => choice.id === rule.service);
    parts.push(rule.service ? (own ? label(own) : rule.service) : t("settings.notification.common_service"));
    if (rule.quiet_hours) {
      parts.push(
        t("settings.notification.quiet.summary", { start: hhmm(rule.quiet_hours.start), end: hhmm(rule.quiet_hours.end) }),
      );
    }
    return capitalized(parts.join(" · "));
  };

  return (
    <>
      <p className="settings-note settings-intro">{t("settings.notification.help")}</p>

      <h3 className="home-summary-heading">{t("settings.notification.sending_title")}</h3>
      <SettingList>
        <div className="ui-setting-row">
          <span>
            <label className="ui-row-label" htmlFor="notify-service">
              {t("settings.notification.service")}
            </label>
            <span className="ui-row-help">{t("settings.notification.service_help")}</span>
          </span>
          <ServiceSelect
            id="notify-service"
            value={settings.service}
            choices={choices}
            empty={t("settings.none")}
            onChange={(service) => onChange({ ...settings, service })}
          />
        </div>
        <div className="ui-setting-row">
          <span>
            <label className="ui-row-label" htmlFor="notify-other">
              {t("settings.notification.other")}
            </label>
            <span className="ui-row-help">{t("settings.notification.other_help")}</span>
          </span>
          <span className="settings-actions">
            <input
              id="notify-other"
              value={freeService}
              placeholder="notify.mobile_app_…"
              onChange={(event) => setFreeService(event.target.value.trim())}
            />
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
          </span>
        </div>
        <div className="ui-setting-row">
          <label className="ui-row-label" htmlFor="notify-language">
            {t("settings.notification.language")}
          </label>
          <select
            id="notify-language"
            value={settings.language}
            onChange={(event) => onChange({ ...settings, language: event.target.value as Language })}
          >
            {LANGUAGES.map((code) => (
              <option key={code} value={code}>
                {LANGUAGE_NAMES[code]}
              </option>
            ))}
          </select>
        </div>
      </SettingList>

      <h3 className="home-summary-heading">{t("settings.notification.messages_title")}</h3>
      <SettingList>
        {KINDS.filter(
          // Sans batterie ni panneaux, leurs messages n'ont pas lieu d'être (sauf déjà activés).
          (kind) =>
            settings[kind].enabled ||
            ((kind !== "battery_full" || features.battery) && (kind !== "forecast_drop" || features.solar)),
        ).map((kind) => {
          const rule = settings[kind];
          const test = tests[kind] ?? { status: "idle" };
          const service = rule.service ?? settings.service;
          const title = t(`settings.notification.kinds.${kind}.title`);
          return (
            <div key={kind} role="group" aria-label={title} className="notification-item">
              <Switch
                label={title}
                description={t(`settings.notification.kinds.${kind}.help`)}
                checked={rule.enabled}
                onChange={(enabled) => setRule(kind, { enabled })}
              />
              {rule.enabled && (
                <details className="settings-details notification-options">
                  <summary>
                    <span className="ui-row-help">{summary(kind)}</span>
                    <Icon name="chevron-right" size={18} />
                  </summary>
                  {kind === "recommendation" && (
                    <div className="ui-setting-row">
                      <label className="ui-row-label" htmlFor="notify-cadence">
                        {t("settings.notification.cadence.label")}
                      </label>
                      <span className="settings-actions settings-actions-wrap">
                        <select
                          id="notify-cadence"
                          value={settings.recommendation.cadence}
                          onChange={(event) =>
                            setRule("recommendation", { cadence: event.target.value as RecommendationRule["cadence"] })
                          }
                        >
                          <option value="every_run">{t("settings.notification.cadence.every_run")}</option>
                          <option value="when_changed">{t("settings.notification.cadence.when_changed")}</option>
                          <option value="daily">{t("settings.notification.cadence.daily")}</option>
                        </select>
                        {settings.recommendation.cadence === "daily" && (
                          <label className="settings-inline">
                            {t("settings.notification.cadence.at")}{" "}
                            <input
                              type="time"
                              value={hhmm(settings.recommendation.daily_at)}
                              onChange={(event) =>
                                event.target.value && setRule("recommendation", { daily_at: event.target.value })
                              }
                            />
                          </label>
                        )}
                      </span>
                    </div>
                  )}
                  {kind === "week" && (
                    <div className="ui-setting-row">
                      <span className="ui-row-label" id="notify-week-days">
                        {t("settings.notification.week.days")}
                      </span>
                      <span className="notification-weekdays" role="group" aria-labelledby="notify-week-days">
                        {WEEKDAYS.map((code, day) => {
                          const checked = settings.week.weekdays.includes(day);
                          return (
                            <label key={code} className="settings-inline">
                              <input
                                type="checkbox"
                                checked={checked}
                                // Au moins un jour : le dernier coché ne se décoche pas.
                                disabled={checked && settings.week.weekdays.length === 1}
                                onChange={(event) =>
                                  setRule("week", {
                                    weekdays: event.target.checked
                                      ? [...settings.week.weekdays, day].sort((a, b) => a - b)
                                      : settings.week.weekdays.filter((d) => d !== day),
                                  })
                                }
                              />{" "}
                              {t(`cycle.weekdays.${code}`)}
                            </label>
                          );
                        })}
                      </span>
                    </div>
                  )}
                  {kind === "week" && (
                    <div className="ui-setting-row">
                      <span className="ui-row-label">{t("settings.notification.week.at")}</span>
                      <label className="settings-inline">
                        {t("settings.notification.cadence.at")}{" "}
                        <input
                          type="time"
                          value={hhmm(settings.week.at)}
                          onChange={(event) => event.target.value && setRule("week", { at: event.target.value })}
                        />
                      </label>
                    </div>
                  )}
                  <div className="ui-setting-row">
                    <label className="ui-row-label" htmlFor={`notify-service-${kind}`}>
                      {t("settings.notification.own_service")}
                    </label>
                    <ServiceSelect
                      id={`notify-service-${kind}`}
                      value={rule.service}
                      choices={choices}
                      empty={t("settings.notification.common_service")}
                      onChange={(value) => setRule(kind, { service: value })}
                    />
                  </div>
                  <Switch
                    label={t("settings.notification.quiet.label")}
                    checked={rule.quiet_hours !== null}
                    onChange={(on) => setRule(kind, { quiet_hours: on ? DEFAULT_QUIET : null })}
                  />
                  {rule.quiet_hours !== null && (
                    <div className="ui-setting-row settings-times">
                      <label className="settings-inline">
                        {t("settings.notification.quiet.from")}{" "}
                        <input
                          type="time"
                          value={hhmm(rule.quiet_hours.start)}
                          onChange={(event) =>
                            event.target.value &&
                            setRule(kind, { quiet_hours: { ...rule.quiet_hours!, start: event.target.value } })
                          }
                        />
                      </label>
                      <label className="settings-inline">
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
                    </div>
                  )}
                  <div className="settings-foot">
                    <span>
                      {test.status === "sent" && (
                        <span role="status" className="settings-ok">
                          {t("settings.notification.sent", { message: test.message })}
                        </span>
                      )}
                      {test.status === "failed" && (
                        <span role="alert">{t(`settings.notification.failure.${test.reason}`)}</span>
                      )}
                    </span>
                    <button
                      type="button"
                      disabled={service === null || test.status === "sending"}
                      aria-label={t("settings.notification.test_of", { name: title })}
                      onClick={() => void onTest(kind)}
                    >
                      {t(test.status === "sending" ? "settings.notification.sending" : "settings.notification.test")}
                    </button>
                  </div>
                </details>
              )}
            </div>
          );
        })}
      </SettingList>
    </>
  );
}
