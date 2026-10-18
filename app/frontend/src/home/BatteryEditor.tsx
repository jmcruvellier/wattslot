// Réglages de la batterie (lot 3.3) : puissances (0,5 C sans réglage), plancher, plage active et
// charge complète périodique. Plusieurs batteries sont vues comme une seule par le calcul.

import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import { C_RATE, DEFAULT_BATTERY, type BatterySettings, type FloorRange } from "./configuration";

const HOURS = Array.from({ length: 25 }, (_, hour) => hour);

function Power({ label, value, automatic, onChange }: {
  label: string;
  value: number | null;
  automatic: number; // puissance par défaut (0,5 C), en indication
  onChange: (value: number | null) => void;
}) {
  return (
    <label>
      {label}{" "}
      <input
        type="number"
        min="0"
        step="10"
        placeholder={String(Math.round(automatic))}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
      />{" "}
      W
    </label>
  );
}

function Hour({ label, value, from, to, onChange }: {
  label: string;
  value: number;
  from: number;
  to: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {label}{" "}
      <select value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {HOURS.filter((hour) => hour >= from && hour <= to).map((hour) => (
          <option key={hour} value={hour}>
            {hour} h
          </option>
        ))}
      </select>
    </label>
  );
}

export default function BatteryEditor({ battery, capacityKwh, onChange }: {
  battery: BatterySettings | null;
  capacityKwh: number;
  onChange: (battery: BatterySettings | null) => void;
}) {
  const { t } = useI18n();
  const settings = battery ?? DEFAULT_BATTERY;
  const set = (change: Partial<BatterySettings>) => onChange({ ...settings, ...change });
  const automatic = capacityKwh * C_RATE * 1000;

  return (
    <div>
      <p>{t("battery.intro", { capacity: capacityKwh })}</p>
      {battery === null && <p>{t("battery.defaults")}</p>}
      <p>
        <Power
          label={t("battery.charge")}
          value={settings.charge_max_w}
          automatic={automatic}
          onChange={(charge_max_w) => set({ charge_max_w })}
        />{" "}
        <Power
          label={t("battery.discharge")}
          value={settings.discharge_max_w}
          automatic={automatic}
          onChange={(discharge_max_w) => set({ discharge_max_w })}
        />
      </p>
      <p>{t("battery.power_hint")}</p>
      <p>
        <label>
          {t("battery.floor")}{" "}
          <input
            type="number"
            min="0"
            max="100"
            step="1"
            value={settings.floor_percent}
            onChange={(event) => set({ floor_percent: Number(event.target.value) })}
          />{" "}
          %
        </label>
        <Hint text={t("battery.floor_hint")} />
      </p>
      <Advanced
        modified={
          battery !== null &&
          ((battery.floor_ranges ?? []).length > 0 ||
            battery.active_from_hour !== DEFAULT_BATTERY.active_from_hour ||
            battery.active_to_hour !== DEFAULT_BATTERY.active_to_hour ||
            battery.full_charge_every_days !== DEFAULT_BATTERY.full_charge_every_days)
        }
      >
      <ul aria-label={t("battery.floor_ranges")}>
        {(settings.floor_ranges ?? []).map((range, index) => {
          const ranges = settings.floor_ranges ?? [];
          const setRange = (change: Partial<FloorRange>) =>
            set({ floor_ranges: ranges.map((r, i) => (i === index ? { ...r, ...change } : r)) });
          return (
            <li key={index} aria-label={t("battery.floor_range", { number: index + 1 })}>
              <Hour label={t("battery.from")} value={range.start_hour} from={0} to={23} onChange={(start_hour) => setRange({ start_hour })} />{" "}
              <Hour label={t("battery.to")} value={range.end_hour} from={1} to={24} onChange={(end_hour) => setRange({ end_hour })} />{" "}
              <label>
                {t("battery.not_below")}{" "}
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  value={range.percent}
                  onChange={(event) => setRange({ percent: Number(event.target.value) })}
                />{" "}
                %
              </label>{" "}
              <button type="button" onClick={() => set({ floor_ranges: ranges.filter((_, i) => i !== index) })}>
                {t("battery.remove_range")}
              </button>
            </li>
          );
        })}
        <li>
          <button
            type="button"
            onClick={() =>
              set({ floor_ranges: [...(settings.floor_ranges ?? []), { start_hour: 0, end_hour: 6, percent: 20 }] })
            }
          >
            {t("battery.add_range")}
          </button>
        </li>
      </ul>
      <p>
        {t("battery.active")}{" "}
        <Hour label={t("battery.from")} value={settings.active_from_hour} from={0} to={23} onChange={(active_from_hour) => set({ active_from_hour })} />{" "}
        <Hour label={t("battery.to")} value={settings.active_to_hour} from={1} to={24} onChange={(active_to_hour) => set({ active_to_hour })} />
      </p>
      <p>
        <label>
          <input
            type="checkbox"
            checked={settings.full_charge_every_days !== null}
            onChange={(event) => set({ full_charge_every_days: event.target.checked ? 7 : null })}
          />{" "}
          {t("battery.full_charge")}
        </label>{" "}
        {settings.full_charge_every_days !== null && (
          <label>
            {t("battery.every")}{" "}
            <input
              type="number"
              min="1"
              step="1"
              value={settings.full_charge_every_days}
              onChange={(event) => set({ full_charge_every_days: Math.max(1, Number(event.target.value)) })}
            />{" "}
            {t("battery.days")}
          </label>
        )}
      </p>
      </Advanced>
      {battery !== null && (
        <button type="button" onClick={() => onChange(null)}>
          {t("battery.reset")}
        </button>
      )}
    </div>
  );
}
