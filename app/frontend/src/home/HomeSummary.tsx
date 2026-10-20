// Ma maison en phrases (lot 6b.5), rédigées à partir de la configuration et de la maison
// enregistrées : « L'essentiel » (priorité, contrat, panneaux, batterie) et « Appareils » (placés au
// meilleur moment, suivis seulement). Un clic ouvre la feuille du réglage.

import { useState } from "react";

import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n/translate";
import Button from "../ui/Button";
import Icon from "../ui/Icon";
import SettingRow, { SettingList } from "../ui/SettingRow";
import { DEFAULT_BATTERY, type Configuration } from "./configuration";
import { deviceText, direction, list, PLACED, tariffText } from "./summaryText";
import type { HomeDevice } from "./types";

// Feuilles de « L'essentiel » ; un appareil s'ouvre par sa clé.
export type Essential = "objective" | "tariff" | "solar" | "battery";

export interface HomeData {
  devices: HomeDevice[];
  configuration: Configuration;
}

export function Essentials({ data, onOpen }: { data: HomeData; onOpen: (sheet: Essential) => void }) {
  const { language, t } = useI18n();
  const { code: currency } = useCurrency();
  const { devices, configuration } = data;
  const preset = configuration.objective?.preset ?? "cost";
  const solar = configuration.devices.filter((s) => s.behavior === "ProductionBehavior");
  const arrays = solar.flatMap((s) => s.panels?.arrays ?? []);
  const batteries = devices.filter((device) => device.kind === "Battery");
  const capacity = batteries.reduce((sum, device) => sum + (device.capacity_kwh ?? 0), 0);
  const battery = configuration.battery ?? DEFAULT_BATTERY;

  const panelsText = () => {
    if (arrays.length === 0) return t("home_summary.panels.undescribed");
    const kwp = formatNumber(language, Math.round(arrays.reduce((sum, array) => sum + array.kwp, 0) * 10) / 10);
    const facing = [...new Set(arrays.map((array) => t(`home_summary.direction.${direction(array.azimuth)}`)))];
    return t("home_summary.panels.fields", { count: arrays.length, directions: list(facing, t), kwp });
  };

  return (
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
  );
}

// Au-delà, un champ de recherche filtre le groupe (souvent des dizaines de prises).
const SEARCH_FROM = 8;

// Nom comparé sans majuscules ni accents.
const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Groupe replié de « Appareils » : une ligne qui le résume, ses appareils dépliés dessous.
function Folded({ label, help, rows, onOpen }: {
  label: string;
  help: string;
  rows: { key: string; name: string }[];
  onOpen: (key: string) => void;
}) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const wanted = fold(search.trim());
  const shown = wanted ? rows.filter((row) => fold(row.name).includes(wanted)) : rows;
  return (
    <details className="home-followed">
      <summary>
        <span>
          <span className="ui-row-label">{label}</span>
          <span className="ui-row-help">{help}</span>
        </span>
        <Icon name="chevron-right" size={18} />
      </summary>
      {rows.length > SEARCH_FROM && (
        <input
          type="search"
          className="home-search"
          aria-label={t("home_summary.search")}
          placeholder={t("home_summary.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      )}
      <SettingList>
        {shown.map((row) => (
          <SettingRow key={row.key} label={row.name} onOpen={() => onOpen(row.key)} />
        ))}
      </SettingList>
    </details>
  );
}

export function Devices({
  data,
  proposed,
  onOpen,
  onAdd,
  onRefresh,
  refreshing = false,
}: {
  data: HomeData;
  proposed: { key: string; name: string }[]; // proposés par HA, pas encore suivis
  onOpen: (key: string) => void;
  onAdd: () => void;
  onRefresh?: () => void; // relire HA (absent tant que HA n'a pas répondu)
  refreshing?: boolean;
}) {
  const { language, t } = useI18n();
  const { devices, configuration } = data;
  const names = new Map(devices.map((device) => [device.key, device.name]));
  const name = (key: string) => names.get(key) ?? key;
  const placed = configuration.devices.filter((s) => PLACED.has(s.behavior) && s.planned);
  const followed = configuration.devices.filter(
    (s) => s.behavior === "UncontrolledBehavior" || (PLACED.has(s.behavior) && !s.planned),
  );
  // Production, réseau et batterie : réglés dans « L'essentiel », leurs capteurs ici.
  const installation = configuration.devices.filter((s) => !placed.includes(s) && !followed.includes(s));
  const rows = (list: typeof placed) => list.map((s) => ({ key: s.key, name: name(s.key) }));

  const namesText = (all: string[]) => {
    // Jusqu'à quatre, tous nommés ; au-delà, trois et le nombre des autres.
    const shown = all.slice(0, all.length <= 4 ? 4 : 3);
    const rest = all.length - shown.length;
    return rest > 0 ? t("home_summary.followed_more", { names: shown.join(", "), count: rest }) : list(shown, t);
  };

  return (
    <>
      {placed.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("home_summary.placed")}</h3>
          <SettingList>
            {placed.map((settings) => (
              <SettingRow
                key={settings.key}
                label={name(settings.key)}
                description={deviceText(settings, names, t, language)}
                onOpen={() => onOpen(settings.key)}
              />
            ))}
          </SettingList>
        </>
      )}

      {followed.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("home_summary.followed")}</h3>
          {/* Souvent des dizaines de prises : repliées, une ligne qui les nomme. */}
          <Folded
            label={namesText(followed.map((s) => name(s.key)))}
            help={t("home_summary.followed_help")}
            rows={rows(followed)}
            onOpen={onOpen}
          />
        </>
      )}

      {installation.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("home_summary.installation")}</h3>
          <Folded
            label={namesText(installation.map((s) => name(s.key)))}
            help={t("home_summary.installation_help")}
            rows={rows(installation)}
            onOpen={onOpen}
          />
        </>
      )}

      {proposed.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("home_summary.proposed")}</h3>
          <Folded
            label={namesText(proposed.map((p) => p.name))}
            help={t("home_summary.proposed_help")}
            rows={proposed}
            onOpen={onOpen}
          />
        </>
      )}

      <p className="home-devices-actions">
        <Button icon="plus" onClick={onAdd}>
          {t("home_summary.add")}
        </Button>
        {onRefresh && (
          <Button variant="quiet" onClick={onRefresh} disabled={refreshing}>
            {t("home.refresh")}
          </Button>
        )}
      </p>
    </>
  );
}
