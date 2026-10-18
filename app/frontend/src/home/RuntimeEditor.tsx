// Durée de fonctionnement à placer (lot 3.4) : vitesses (sans vitesse réglée, une seule, de la
// puissance mesurée sur l'historique), heures minimales et jours sautables par saison, démarrages.

import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import { DEFAULT_RUNTIME, SEASONS, type RuntimeSettings, type Speed } from "./configuration";

function Number_({ label, value, min, step, onChange }: {
  label: string;
  value: number;
  min: number;
  step: string;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {label}{" "}
      <input
        type="number"
        min={min}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value === "" ? min : Number(event.target.value))}
      />
    </label>
  );
}

export default function RuntimeEditor({ runtime, name, onChange }: {
  runtime: RuntimeSettings | null;
  name: string; // nom de l'équipement, pour les noms accessibles
  onChange: (runtime: RuntimeSettings | null) => void;
}) {
  const { t } = useI18n();
  const settings = runtime ?? DEFAULT_RUNTIME;
  const set = (change: Partial<RuntimeSettings>) => onChange({ ...settings, ...change });
  const setSpeed = (index: number, change: Partial<Speed>) =>
    set({ speeds: settings.speeds.map((s, i) => (i === index ? { ...s, ...change } : s)) });

  // Avancés : vitesses (mesurées sans réglage), jours sautables, démarrages.
  const modified =
    runtime !== null &&
    (runtime.speeds.length > 0 ||
      runtime.max_starts !== DEFAULT_RUNTIME.max_starts ||
      SEASONS.some((season) => runtime.skip_days[season] !== DEFAULT_RUNTIME.skip_days[season]));

  return (
    <fieldset aria-label={t("runtime.title", { device: name })}>
      <legend>{t("runtime.title", { device: name })}</legend>
      <p>
        {t("runtime.minimum_hours")}{" "}
        {SEASONS.map((season) => (
          <Number_
            key={season}
            label={t(`runtime.seasons.${season}`)}
            value={settings.minimum_hours[season] ?? 0}
            min={0}
            step="1"
            onChange={(hours) => set({ minimum_hours: { ...settings.minimum_hours, [season]: hours } })}
          />
        ))}
        <Hint text={t("runtime.minimum_hours_hint")} />
      </p>
      <Advanced modified={modified}>
      {settings.speeds.length === 0 && <p>{t("runtime.measured")}</p>}
      <ul>
        {settings.speeds.map((speed, index) => (
          <li key={index} aria-label={t("runtime.speed", { number: index + 1 })}>
            <label>
              {t("runtime.speed_name")}{" "}
              <input value={speed.name} onChange={(event) => setSpeed(index, { name: event.target.value })} />
            </label>{" "}
            <Number_ label={t("runtime.power")} value={speed.kw} min={0} step="0.001" onChange={(kw) => setSpeed(index, { kw })} /> kW{" "}
            <button type="button" onClick={() => set({ speeds: settings.speeds.filter((_, i) => i !== index) })}>
              {t("runtime.remove_speed")}
            </button>
          </li>
        ))}
        <li>
          <button type="button" onClick={() => set({ speeds: [...settings.speeds, { name: "", kw: 0.5 }] })}>
            {t("runtime.add_speed")}
          </button>
        </li>
      </ul>
      <p>
        {t("runtime.skip_days")}{" "}
        {SEASONS.map((season) => (
          <Number_
            key={season}
            label={t(`runtime.seasons.${season}`)}
            value={settings.skip_days[season] ?? 0}
            min={0}
            step="1"
            onChange={(days) => set({ skip_days: { ...settings.skip_days, [season]: days } })}
          />
        ))}
      </p>
      <p>
        <Number_
          label={t("runtime.max_starts")}
          value={settings.max_starts}
          min={1}
          step="1"
          onChange={(max_starts) => set({ max_starts: Math.max(1, max_starts) })}
        />
      </p>
      </Advanced>
      {runtime !== null && (
        <button type="button" onClick={() => onChange(null)}>
          {t("runtime.reset")}
        </button>
      )}
    </fieldset>
  );
}
