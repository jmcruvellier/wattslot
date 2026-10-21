// Objectif du calcul (lot 3.6, point n° 3) : un préréglage, ou des poids libres sous « Réglages
// avancés » (lot 4.7), avec l'entité d'intensité carbone. Poids en équivalent euros : un kWh y
// vaut le prix moyen du jour.

import Advanced from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import { useHomeFeatures } from "./features";
import { PRESETS, type ObjectiveSettings, type Preset, type Weights } from "./configuration";

const DEFAULT_WEIGHTS: Weights = { cost: 1, grid_import: 0, grid_export: 0 };

export default function ObjectiveEditor({ objective, onChange }: {
  objective: ObjectiveSettings | null;
  onChange: (objective: ObjectiveSettings | null) => void;
}) {
  const { t } = useI18n();
  const preset = objective?.preset ?? "cost";
  const weights = objective?.weights ?? DEFAULT_WEIGHTS;
  const co2Entity = objective?.co2_entity ?? null;
  // CO₂ : seulement avec une entité d'intensité du réseau ; poids libres : réglés dans les
  // réglages avancés, puis proposés dans la liste.
  const features = useHomeFeatures();
  // Sans panneaux, ni autoconsommation ni surplus ; sans batterie, pas de critère « batterie » ;
  // un choix déjà fait reste proposé, pour pouvoir le changer.
  const choices = PRESETS.filter(
    (p) =>
      (p !== "custom" || preset === "custom") &&
      (p !== "co2" || co2Entity) &&
      (p !== "self_consumption" || features.solar || preset === p),
  );
  const criteria = (["cost", "grid_import", "grid_export", "co2", "battery"] as const).filter(
    (name) =>
      (name !== "co2" || co2Entity) &&
      (name !== "grid_export" || features.solar) &&
      (name !== "battery" || features.battery),
  );
  const setWeight = (name: keyof Weights, value: number) =>
    onChange({ preset: "custom", weights: { ...weights, [name]: Math.max(0, value) }, co2_entity: co2Entity });

  return (
    <div>
      {objective === null && <p>{t("objective.defaults")}</p>}
      <label>
        {t("objective.preset")}{" "}
        <select
          value={preset}
          onChange={(event) => {
            const chosen = event.target.value as Preset;
            onChange({ preset: chosen, weights: chosen === "custom" ? weights : null, co2_entity: co2Entity });
          }}
        >
          {choices.map((choice) => (
            <option key={choice} value={choice}>
              {t(`objective.presets.${choice}`)}
            </option>
          ))}
        </select>
      </label>
      <p>{t(`objective.hints.${preset}`)}</p>
      <Advanced modified={preset === "custom" || co2Entity !== null}>
      <p>
        <label>
          {t("objective.co2_entity")}{" "}
          <input
            placeholder="sensor.co2_intensity"
            value={co2Entity ?? ""}
            onChange={(event) =>
              onChange({
                preset: event.target.value || preset !== "co2" ? preset : "cost",
                weights: objective?.weights ?? null,
                co2_entity: event.target.value.trim() || null,
              })
            }
          />
        </label>{" "}
        {t("objective.co2_hint")}
      </p>
        <fieldset aria-label={t("objective.weights")}>
          <legend>{t("objective.weights")}</legend>
          <p>{t("objective.weights_hint")}</p>
          {criteria.map((name) => (
            <label key={name}>
              {t(`objective.weight.${name}`)}{" "}
              <input
                type="number"
                min="0"
                step="0.1"
                value={weights[name] ?? 0}
                onChange={(event) => setWeight(name, Number(event.target.value))}
              />{" "}
            </label>
          ))}
        </fieldset>
      </Advanced>
    </div>
  );
}
