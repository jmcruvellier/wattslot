// Feuille « Batterie » de « L'essentiel » : les réglages de la maison, suivis par toutes les
// batteries, puis, quand il y en a plusieurs, les réglages propres à celles qui diffèrent. Le
// calcul voit toujours les batteries comme une seule (backend : battery_settings.combine).
// Chargée à l'ouverture de la feuille.

import { useI18n } from "../i18n/I18nProvider";
import BatteryEditor from "./BatteryEditor";
import { DEFAULT_BATTERY, type BatterySettings, type Configuration } from "./configuration";
import type { HomeDevice } from "./types";

export default function BatteriesEditor({
  draft,
  devices,
  threePhase,
  onChange,
}: {
  draft: Configuration;
  devices: HomeDevice[];
  threePhase: boolean;
  onChange: (next: Configuration) => void;
}) {
  const { t } = useI18n();
  const batteries = devices.filter((device) => device.kind === "Battery");
  const capacity = batteries.reduce((sum, device) => sum + (device.capacity_kwh ?? 0), 0);
  const house = draft.battery ?? null;
  const setOwn = (key: string, battery: BatterySettings | null) =>
    onChange({
      ...draft,
      devices: draft.devices.map((settings) =>
        settings.key === key ? { ...settings, battery, default: false } : settings,
      ),
    });

  return (
    <div className="expert-form">
      <BatteryEditor
        battery={house}
        capacityKwh={capacity}
        threePhase={threePhase}
        onChange={(battery) => onChange({ ...draft, battery })}
      />
      {batteries.length > 1 && (
        <>
          <h3>{t("battery.own_title")}</h3>
          <p>{t("battery.own_help")}</p>
          {batteries.map((device) => {
            const own = draft.devices.find((settings) => settings.key === device.key)?.battery ?? null;
            return (
              <section key={device.key} aria-label={device.name}>
                <h4>{device.name}</h4>
                {own === null ? (
                  <button type="button" onClick={() => setOwn(device.key, { ...(house ?? DEFAULT_BATTERY) })}>
                    {t("battery.own_start")}
                  </button>
                ) : (
                  <BatteryEditor
                    own
                    battery={own}
                    capacityKwh={device.capacity_kwh ?? 0}
                    threePhase={threePhase}
                    onChange={(battery) => setOwn(device.key, battery)}
                  />
                )}
              </section>
            );
          })}
        </>
      )}
    </div>
  );
}
