// Capteurs publiés dans Home Assistant (expérimental) : la prévision de consommation de la
// maison, écrite par le serveur dans trois capteurs (/api/settings/sensors). L'interrupteur
// enregistre tout de suite, sans « Enregistrer » : la réponse dit si Home Assistant a accepté
// l'écriture. Sans réponse du serveur à l'ouverture, la section n'est pas affichée.

import { useEffect, useState } from "react";

import { getJson, putJson } from "../api";
import { zoned } from "../i18n/homeTime";
import { useI18n } from "../i18n/I18nProvider";
import { SettingList } from "../ui/SettingRow";
import Switch from "../ui/Switch";

export interface PublishedSensorsState {
  consumption_forecast: boolean;
  entities: string[];
  available: boolean; // faux : pas de connexion à Home Assistant réglée
  published_at: string | null;
  error: "refused" | "unreachable" | "unknown" | null;
}

export default function PublishedSensors() {
  const { language, t } = useI18n();
  const [state, setState] = useState<PublishedSensorsState | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getJson<PublishedSensorsState>("api/settings/sensors", controller.signal)
      .then(setState)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  if (state === null) return null;

  const change = async (consumption_forecast: boolean) => {
    setSaving(true);
    setFailed(false);
    try {
      setState(await putJson<PublishedSensorsState>("api/settings/sensors", { consumption_forecast }));
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <h3 id="published-sensors" className="home-summary-heading">
        {t("settings.sensors.title")}
        <span className="settings-aside"> · {t("settings.sensors.experimental")}</span>
      </h3>
      <p className="settings-note settings-intro">{t("settings.sensors.help")}</p>
      <SettingList>
        <Switch
          label={t("settings.sensors.consumption_forecast")}
          description={t("settings.sensors.consumption_forecast_help")}
          checked={state.consumption_forecast}
          disabled={saving}
          onChange={(checked) => void change(checked)}
        />
      </SettingList>
      {failed && (
        <p role="alert" className="settings-note settings-danger">
          {t("settings.failed")}
        </p>
      )}
      {state.consumption_forecast && (
        <>
          <ul className="settings-note published-sensors">
            {state.entities.map((entity) => (
              <li key={entity}>
                <code>{entity}</code>
              </li>
            ))}
          </ul>
          {!state.available && (
            <p role="status" className="settings-note">
              {t("settings.sensors.not_connected")}
            </p>
          )}
          {state.error && (
            <p role="alert" className="settings-note settings-danger">
              {t(`settings.sensors.error_${state.error}`)}
            </p>
          )}
          {!state.error && state.published_at && (
            <p role="status" className="settings-note settings-ok">
              {t("settings.sensors.published", {
                time: new Date(state.published_at).toLocaleTimeString(language, {
                  ...zoned(),
                  hour: "2-digit",
                  minute: "2-digit",
                }),
              })}
            </p>
          )}
        </>
      )}
    </>
  );
}
