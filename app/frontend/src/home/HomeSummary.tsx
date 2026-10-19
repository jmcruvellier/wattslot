// Ma maison en phrases (lot 6b.5) : priorité, contrat, panneaux, batterie, appareils placés au
// meilleur moment et appareils suivis seulement, rédigés à partir de la configuration et de la
// maison enregistrées. Un clic ouvre le réglage concerné dans « Réglages détaillés ».

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n/translate";
import Button from "../ui/Button";
import SettingRow, { SettingList } from "../ui/SettingRow";
import { DEFAULT_BATTERY, type Configuration } from "./configuration";
import { deviceText, direction, list, PLACED, tariffText } from "./summaryText";
import type { HomeDevice, HomeModel } from "./types";
import StateMessage from "../ui/StateMessage";

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; devices: HomeDevice[]; configuration: Configuration };

export default function HomeSummary({ version, onOpen }: { version: number; onOpen: (anchor: string) => void }) {
  const { language, t } = useI18n();
  const { code: currency } = useCurrency();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0); // « Réessayer »

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
  }, [version, attempt]);

  if (load.status === "loading") return <StateMessage kind="loading" title={t("home_summary.loading")} />;
  if (load.status === "error") {
    return (
      <StateMessage
        kind="error"
        title={t("home_summary.error")}
        onRetry={() => {
          setLoad({ status: "loading" });
          setAttempt((count) => count + 1);
        }}
      />
    );
  }
  const { devices, configuration } = load;
  const names = new Map(devices.map((device) => [device.key, device.name]));
  const name = (key: string) => names.get(key) ?? key;
  const preset = configuration.objective?.preset ?? "cost";

  const solar = configuration.devices.filter((s) => s.behavior === "ProductionBehavior");
  const arrays = solar.flatMap((s) => s.panels?.arrays ?? []);
  const batteries = devices.filter((device) => device.kind === "Battery");
  const capacity = batteries.reduce((sum, device) => sum + (device.capacity_kwh ?? 0), 0);
  const battery = configuration.battery ?? DEFAULT_BATTERY;
  const placed = configuration.devices.filter((s) => PLACED.has(s.behavior) && s.planned);
  const followed = configuration.devices.filter(
    (s) => s.behavior === "UncontrolledBehavior" || (PLACED.has(s.behavior) && !s.planned),
  );

  const panelsText = () => {
    if (arrays.length === 0) return t("home_summary.panels.undescribed");
    const kwp = formatNumber(language, Math.round(arrays.reduce((sum, array) => sum + array.kwp, 0) * 10) / 10);
    const facing = [...new Set(arrays.map((array) => t(`home_summary.direction.${direction(array.azimuth)}`)))];
    return t("home_summary.panels.fields", { count: arrays.length, directions: list(facing, t), kwp });
  };

  const followedText = () => {
    // Jusqu'à quatre, tous nommés ; au-delà, trois et le nombre des autres.
    const shown = followed.slice(0, followed.length <= 4 ? 4 : 3).map((s) => name(s.key));
    const rest = followed.length - shown.length;
    return rest > 0 ? t("home_summary.followed_more", { names: shown.join(", "), count: rest }) : list(shown, t);
  };

  return (
    <section className="home-summary" aria-labelledby="home-summary-title">
      <h2 id="home-summary-title" className="visually-hidden">
        {t("home_summary.title")}
      </h2>
      <SettingList>
        <SettingRow
          label={t("home_summary.priority")}
          description={t(`home_summary.presets.${preset}`)}
          onOpen={() => onOpen("objective")}
        />
        <SettingRow
          label={t("home_summary.contract.title")}
          description={tariffText(configuration.tariff, t, language, currency)}
          onOpen={() => onOpen("tariff")}
        />
        {solar.length > 0 && (
          <SettingRow label={t("home_summary.panels.title")} description={panelsText()} onOpen={() => onOpen("solar")} />
        )}
        {batteries.length > 0 && (
          <SettingRow
            label={t("home_summary.battery.title")}
            description={[
              t("home_summary.battery.floor", {
                kwh: formatNumber(language, capacity, 1),
                pct: formatNumber(language, battery.floor_percent, 0),
              }),
              battery.full_charge_every_days
                ? t("home_summary.battery.full_charge", { days: battery.full_charge_every_days })
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
            onOpen={() => onOpen("battery")}
          />
        )}
      </SettingList>

      {placed.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("home_summary.placed")}</h3>
          <SettingList>
            {placed.map((settings) => (
              <SettingRow
                key={settings.key}
                label={name(settings.key)}
                description={deviceText(settings, names, t, language)}
                onOpen={() => onOpen(`settings-${settings.key}`)}
              />
            ))}
          </SettingList>
        </>
      )}

      {followed.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("home_summary.followed")}</h3>
          <SettingList>
            <SettingRow
              label={followedText()}
              description={t("home_summary.followed_help")}
              onOpen={() => onOpen(`settings-${followed[0].key}`)}
            />
          </SettingList>
        </>
      )}

      <p>
        <Button icon="plus" onClick={() => onOpen("add-device")}>
          {t("home_summary.add")}
        </Button>
      </p>
    </section>
  );
}
