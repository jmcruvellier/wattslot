// Besoin d'énergie avant une échéance (lot 3.4) : énergie, fenêtre, puissance maximale, mode
// continu ou par paliers, chaque jour ou seulement quand une tâche de HA le demande.

import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import { DEFAULT_ENERGY_NEED, type EnergyNeed } from "./configuration";

function Number_({ label, value, min, max, step, onChange }: {
  label: string;
  value: number;
  min: number;
  max?: number;
  step: string;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {label}{" "}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value === "" ? min : Number(event.target.value))}
      />
    </label>
  );
}

export default function EnergyNeedEditor({ need, name, onChange }: {
  need: EnergyNeed | null;
  name: string; // nom de l'équipement, pour les noms accessibles
  onChange: (need: EnergyNeed | null) => void;
}) {
  const { t } = useI18n();
  const settings = need ?? DEFAULT_ENERGY_NEED;
  const set = (change: Partial<EnergyNeed>) => onChange({ ...settings, ...change });

  return (
    <fieldset aria-label={t("need.title", { device: name })}>
      <legend>{t("need.title", { device: name })}</legend>
      {need === null && <p>{t("need.unset")}</p>}
      <p>
        <Number_ label={t("need.energy")} value={settings.energy_kwh} min={0} step="0.1" onChange={(energy_kwh) => set({ energy_kwh })} /> kWh{" "}
        <Number_ label={t("need.deadline")} value={settings.deadline_hour} min={1} max={24} step="1" onChange={(deadline_hour) => set({ deadline_hour })} /> h{" "}
        <Number_ label={t("need.max_power")} value={settings.max_kw} min={0} step="0.1" onChange={(max_kw) => set({ max_kw })} /> kW
        <Hint text={t("need.hint")} />
      </p>
      <Advanced
        modified={
          need !== null &&
          (need.earliest_hour !== DEFAULT_ENERGY_NEED.earliest_hour || need.steps !== DEFAULT_ENERGY_NEED.steps || need.daily !== DEFAULT_ENERGY_NEED.daily)
        }
      >
      <p>
        <Number_ label={t("need.earliest")} value={settings.earliest_hour} min={0} max={23} step="1" onChange={(earliest_hour) => set({ earliest_hour })} /> h
      </p>
      <p>
        <label>
          <input type="checkbox" checked={settings.steps} onChange={(event) => set({ steps: event.target.checked })} />{" "}
          {t("need.steps")}
        </label>{" "}
        <label>
          <input type="checkbox" checked={settings.daily} onChange={(event) => set({ daily: event.target.checked })} />{" "}
          {t("need.daily")}
        </label>
      </p>
      </Advanced>
      {need !== null && (
        <button type="button" onClick={() => onChange(null)}>
          {t("need.reset")}
        </button>
      )}
    </fieldset>
  );
}
