// Réglages du calcul d'un équipement (lot 3.1, phase 3), ouverts dans sa feuille de « Ma maison » :
// comportement, prise en compte par le calcul et l'éditeur propre au comportement.

import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import { automationFor, BEHAVIORS, CONSTRAINED, isObserved, type Behavior, type DeviceSettings as Settings } from "./configuration";
import ConstraintEditor from "./ConstraintEditor";
import CycleEditor from "./CycleEditor";
import EnergyNeedEditor from "./EnergyNeedEditor";
import PanelsEditor from "./PanelsEditor";
import RuntimeEditor from "./RuntimeEditor";
import type { DeviceKind } from "./types";

export default function DeviceSettings({
  settings,
  kind,
  name,
  others,
  onChange,
}: {
  settings: Settings;
  kind: DeviceKind | null; // null : équipement absent de la maison enregistrée
  name: string;
  others: { key: string; name: string }[]; // autres cycles, pour « démarre après »
  onChange: (update: Partial<Settings>) => void;
}) {
  const { t } = useI18n();
  const choices = kind ? BEHAVIORS[kind] : [settings.behavior];
  return (
    <div className="expert-form">
      <label>
        {t("configuration.behavior")}{" "}
        <select
          value={settings.behavior}
          disabled={choices.length < 2}
          onChange={(event) => {
            const behavior = event.target.value as Behavior;
            onChange({
              behavior,
              automation: automationFor(behavior),
              runtime: behavior === "RuntimeBehavior" ? settings.runtime : null,
              energy: behavior === "EnergyByDeadlineBehavior" ? settings.energy : null,
              constraints: CONSTRAINED.includes(behavior) ? settings.constraints : [],
              after: behavior === "CycleBehavior" ? settings.after : null,
              max_delay_days: behavior === "CycleBehavior" ? settings.max_delay_days : null,
              recurrence: behavior === "CycleBehavior" ? settings.recurrence : null,
            });
          }}
        >
          {choices.map((behavior) => (
            <option key={behavior} value={behavior}>
              {t(`behavior.${behavior}`)}
            </option>
          ))}
        </select>
      </label>
      <Hint text={t(`configuration.behavior_hints.${settings.behavior}`)} />{" "}
      {!isObserved(settings.behavior) && (
        <label>
          <input
            type="checkbox"
            checked={settings.planned}
            onChange={(event) => onChange({ planned: event.target.checked })}
          />{" "}
          {t("configuration.planned")}
          <Hint text={t("configuration.planned_hint")} />
        </label>
      )}
      {settings.behavior === "ProductionBehavior" && (
        <PanelsEditor panels={settings.panels ?? null} name={name} onChange={(panels) => onChange({ panels })} />
      )}
      {settings.behavior === "RuntimeBehavior" && settings.planned && (
        <RuntimeEditor runtime={settings.runtime ?? null} name={name} onChange={(runtime) => onChange({ runtime })} />
      )}
      {settings.behavior === "EnergyByDeadlineBehavior" && settings.planned && (
        <EnergyNeedEditor need={settings.energy ?? null} name={name} onChange={(energy) => onChange({ energy })} />
      )}
      {settings.behavior === "CycleBehavior" && settings.planned && (
        <CycleEditor
          after={settings.after ?? null}
          maxDelayDays={settings.max_delay_days ?? null}
          name={name}
          others={others}
          recurrence={settings.recurrence ?? null}
          onChange={(cycle) => onChange(cycle)}
        />
      )}
      {CONSTRAINED.includes(settings.behavior) && settings.planned && (
        <Advanced modified={(settings.constraints ?? []).length > 0}>
          <ConstraintEditor
            constraints={settings.constraints ?? []}
            name={name}
            onChange={(constraints) => onChange({ constraints })}
          />
        </Advanced>
      )}
      {settings.default && <p>{t("configuration.default")}</p>}
    </div>
  );
}
