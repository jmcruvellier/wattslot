// Page Réglages (lot 6b.6) : une liste, chaque ligne avec un résumé de son réglage, qui ouvre sa
// sous-page ; les réglages techniques sous « Pour aller plus loin ». Les résumés sont lus à
// l'ouverture ; une réponse manquante laisse la ligne sans résumé.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import type { Health } from "../App";
import { useI18n } from "../i18n/I18nProvider";
import { LANGUAGE_NAMES } from "../i18n/translate";
import { useStatusLevel } from "../nav/status";
import { useUpdateState } from "../nav/updates";
import { routeHash, type Route } from "../nav/routes";
import type { UserRequest } from "../start/RequestsSection";
import { readTheme } from "../theme/theme";
import Icon from "../ui/Icon";
import { SettingList } from "../ui/SettingRow";
import type { NotificationKind, NotificationSettings } from "./NotificationSettings";
import type { PlanningSettings, SettingsChoices } from "./SettingsScreen";

const KINDS: NotificationKind[] = ["recommendation", "device_now", "plan_gap", "battery_full", "forecast_drop"];

interface Summaries {
  notifications?: NotificationSettings;
  choices?: SettingsChoices;
  planning?: PlanningSettings;
  requests?: UserRequest[];
  health?: Health;
}

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function read<T>(url: string, signal: AbortSignal): Promise<T | undefined> {
  return getJson<T>(url, signal).catch(() => undefined);
}

function LinkRow({ route, label, description }: { route: Route; label: string; description?: string | null }) {
  return (
    <a className="ui-setting-row ui-setting-row-open" href={routeHash(route)}>
      <span>
        <span className="ui-row-label">{label}</span>
        {description && <span className="ui-row-help">{description}</span>}
      </span>
      <Icon name="chevron-right" size={18} />
    </a>
  );
}

export default function SettingsHome() {
  const { language, t } = useI18n();
  const [found, setFound] = useState<Summaries>({});
  const status = useStatusLevel();
  const update = useUpdateState();

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      read<NotificationSettings>("api/settings/notifications", controller.signal),
      read<SettingsChoices>("api/settings/choices", controller.signal),
      read<PlanningSettings>("api/settings/planning", controller.signal),
      read<UserRequest[]>("api/requests", controller.signal),
      read<Health>("api/health", controller.signal),
    ]).then(([notifications, choices, planning, requests, health]) => {
      if (!controller.signal.aborted) setFound({ notifications, choices, planning, requests, health });
    });
    return () => controller.abort();
  }, []);

  const notificationsText = () => {
    const settings = found.notifications;
    if (!settings) return null;
    const active = KINDS.filter((kind) => settings[kind].enabled).length;
    if (active === 0) return t("settings_home.notifications_none");
    const service = settings.service;
    const device = found.choices?.notify_services.find((choice) => choice.id === service)?.name ?? service;
    return device
      ? t("settings_home.notifications_on", { count: active, device })
      : t("settings_home.notifications_count", { count: active });
  };

  const requestsText = () => {
    if (!found.requests) return null;
    const open = found.requests.filter((request) => request.status === "open").length;
    return open ? t("settings_home.requests_open", { count: open }) : t("settings_home.requests_none");
  };

  const plannerText = () => {
    const planning = found.planning;
    if (!planning) return null;
    return planning.scheduler_enabled
      ? t("settings_home.scheduler_on", { minute: planning.run_minute })
      : t("settings_home.scheduler_off");
  };

  const connection = found.health?.connections.home_assistant.state;

  return (
    <section className="settings-home" aria-label={t("settings.title")}>
      <SettingList>
        <LinkRow route={{ section: "settings", sub: "notifications" }} label={t("nav.notifications")} description={notificationsText()} />
        <LinkRow route={{ section: "assistant", sub: null }} label={t("settings_home.assistant")} description={t("settings_home.assistant_help")} />
        <LinkRow route={{ section: "assistant", sub: null }} label={t("requests.title")} description={requestsText()} />
        <LinkRow
          route={{ section: "settings", sub: "display" }}
          label={t("settings.appearance.title")}
          description={`${LANGUAGE_NAMES[language]} · ${t(`settings.appearance.themes.${readTheme()}.name`)}`}
        />
      </SettingList>

      <h2 className="home-summary-heading">{t("nav.more")}</h2>
      <SettingList>
        <a className="ui-setting-row ui-setting-row-open" href={routeHash({ section: "settings", sub: "status" })}>
          <span>
            <span className="ui-row-label">{t("nav.status")}</span>
            {status && <span className="ui-row-help">{t(`nav.status_${status}`)}</span>}
            {update.status === "available" && (
              <span className="ui-row-help update-row">{t("updates.row", { version: update.latest.version })}</span>
            )}
          </span>
          <span className="settings-home-status">
            {update.status === "available" && <span className="update-dot" aria-hidden="true" />}
            {status && <span className="status-dot" data-level={status} aria-hidden="true" />}
            <Icon name="chevron-right" size={18} />
          </span>
        </a>
        <LinkRow route={{ section: "settings", sub: "calculation" }} label={t("nav.calculation")} description={plannerText()} />
        <LinkRow route={{ section: "home", sub: "backup" }} label={t("nav.backup")} />
        <LinkRow route={{ section: "home", sub: "library" }} label={t("nav.library")} />
        <LinkRow
          route={{ section: "settings", sub: "connection" }}
          label={t("nav.connection")}
          description={connection ? capitalized(t(`connection.${connection}`)) : null}
        />
      </SettingList>
    </section>
  );
}
