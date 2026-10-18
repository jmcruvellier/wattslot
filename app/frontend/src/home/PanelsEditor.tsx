// Panneaux d'une installation solaire (lot 4.4) : ce qu'il faut pour une prévision Open-Meteo
// calculée par l'application, utilisée seulement sans prévision au tableau Énergie de HA. Un ou
// plusieurs champs (puissance crête, inclinaison, orientation), l'onduleur et le rendement.

import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import type { PanelArray, SolarPanels } from "./configuration";

// Orientations proposées, en degrés de boussole (180 : plein sud).
const ORIENTATIONS = [
  ["north", 0],
  ["north_east", 45],
  ["east", 90],
  ["south_east", 135],
  ["south", 180],
  ["south_west", 225],
  ["west", 270],
  ["north_west", 315],
] as const;

const NEW_ARRAY: PanelArray = { kwp: 3, tilt: 30, azimuth: 180 };
const DEFAULT_EFFICIENCY = 0.9; // backend : solar_panels.SolarPanels

function NumberField({ label, value, min, max, step, onChange }: {
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
        onChange={(event) => {
          const found = Number(event.target.value);
          if (event.target.value !== "" && Number.isFinite(found)) onChange(found);
        }}
      />
    </label>
  );
}

export default function PanelsEditor({ panels, name, onChange }: {
  panels: SolarPanels | null;
  name: string; // nom de l'installation, pour les noms accessibles
  onChange: (panels: SolarPanels | null) => void;
}) {
  const { t } = useI18n();

  if (panels === null) {
    return (
      <fieldset aria-label={t("panels.title", { device: name })}>
        <legend>{t("panels.title", { device: name })}</legend>
        <p>{t("panels.unset")}</p>
        <button type="button" onClick={() => onChange({ arrays: [NEW_ARRAY], inverter_kw: null, efficiency: DEFAULT_EFFICIENCY })}>
          {t("panels.describe")}
        </button>
      </fieldset>
    );
  }

  const setArray = (index: number, change: Partial<PanelArray>) =>
    onChange({
      ...panels,
      arrays: panels.arrays.map((array, at) => (at === index ? { ...array, ...change } : array)),
    });

  return (
    <fieldset aria-label={t("panels.title", { device: name })}>
      <legend>{t("panels.title", { device: name })}</legend>
      <p>{t("panels.help")}</p>
      <ul>
        {panels.arrays.map((array, index) => {
          const known = ORIENTATIONS.some(([, degrees]) => degrees === array.azimuth);
          return (
            <li key={index} aria-label={t("panels.array", { number: index + 1 })}>
              <NumberField
                label={t("panels.kwp")}
                value={array.kwp}
                min={0.1}
                step="0.01"
                onChange={(kwp) => setArray(index, { kwp })}
              />{" "}
              kWc{" "}
              <NumberField
                label={t("panels.tilt")}
                value={array.tilt}
                min={0}
                max={90}
                step="1"
                onChange={(tilt) => setArray(index, { tilt: Math.min(90, Math.max(0, tilt)) })}
              />
              °{" "}
              <label>
                {t("panels.orientation")}{" "}
                <select
                  value={known ? String(array.azimuth) : "custom"}
                  onChange={(event) => {
                    if (event.target.value !== "custom") setArray(index, { azimuth: Number(event.target.value) });
                  }}
                >
                  {ORIENTATIONS.map(([key, degrees]) => (
                    <option key={key} value={String(degrees)}>
                      {t(`panels.orientations.${key}`)}
                    </option>
                  ))}
                  {!known && <option value="custom">{t("panels.degrees", { degrees: array.azimuth })}</option>}
                </select>
              </label>{" "}
              {panels.arrays.length > 1 && (
                <button
                  type="button"
                  onClick={() => onChange({ ...panels, arrays: panels.arrays.filter((_, at) => at !== index) })}
                >
                  {t("panels.remove")}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <button type="button" onClick={() => onChange({ ...panels, arrays: [...panels.arrays, NEW_ARRAY] })}>
        {t("panels.add")}
      </button>
      <Hint text={t("panels.arrays_hint")} />
      <Advanced
        modified={
          panels.inverter_kw !== null ||
          panels.efficiency !== DEFAULT_EFFICIENCY ||
          panels.arrays.some((array) => !ORIENTATIONS.some(([, degrees]) => degrees === array.azimuth))
        }
      >
      <ul>
        {panels.arrays.map((array, index) => (
          <li key={index}>
            <NumberField
              label={t("panels.azimuth", { number: index + 1 })}
              value={array.azimuth}
              min={0}
              max={359}
              step="1"
              onChange={(azimuth) => setArray(index, { azimuth: ((azimuth % 360) + 360) % 360 })}
            />
            °
          </li>
        ))}
      </ul>
      <p>
        <label>
          {t("panels.inverter")}{" "}
          <input
            type="number"
            min={0.1}
            step="0.1"
            value={panels.inverter_kw ?? ""}
            placeholder={t("panels.no_inverter")}
            onChange={(event) => {
              const found = Number(event.target.value);
              onChange({ ...panels, inverter_kw: event.target.value === "" || !(found > 0) ? null : found });
            }}
          />
        </label>{" "}
        kW{" "}
        <NumberField
          label={t("panels.efficiency")}
          value={Math.round(panels.efficiency * 100)}
          min={1}
          max={100}
          step="1"
          onChange={(percent) => onChange({ ...panels, efficiency: Math.min(100, Math.max(1, percent)) / 100 })}
        />{" "}
        %
      </p>
      </Advanced>
      <button type="button" onClick={() => onChange(null)}>
        {t("panels.clear")}
      </button>
    </fieldset>
  );
}
