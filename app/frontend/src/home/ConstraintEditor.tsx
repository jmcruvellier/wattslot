// Contraintes horaires d'un équipement (lot 3.5) : plages interdites, « pas avant », « terminé
// avant » ; chacune dure (jamais violée) ou souple (violée au besoin, signalée).

import { useI18n } from "../i18n/I18nProvider";
import { CONSTRAINT_KINDS, type ConstraintKind, type TimeConstraint } from "./configuration";

function Hour({ label, value, min, max, onChange }: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {label}{" "}
      <input
        type="number"
        min={min}
        max={max}
        step="1"
        value={value}
        onChange={(event) => onChange(event.target.value === "" ? min : Number(event.target.value))}
      />{" "}
      h
    </label>
  );
}

const NEW: Record<ConstraintKind, TimeConstraint> = {
  forbidden: { kind: "forbidden", start_hour: 22, end_hour: 7, hard: true },
  not_before: { kind: "not_before", start_hour: 8, end_hour: 24, hard: true },
  finish_before: { kind: "finish_before", start_hour: 0, end_hour: 18, hard: true },
};

export default function ConstraintEditor({ constraints, name, onChange }: {
  constraints: TimeConstraint[];
  name: string; // nom de l'équipement, pour les noms accessibles
  onChange: (constraints: TimeConstraint[]) => void;
}) {
  const { t } = useI18n();
  const set = (index: number, change: Partial<TimeConstraint>) =>
    onChange(constraints.map((c, i) => (i === index ? { ...c, ...change } : c)));

  return (
    <fieldset aria-label={t("constraint.title", { device: name })}>
      <legend>{t("constraint.title", { device: name })}</legend>
      {constraints.length === 0 && <p>{t("constraint.none")}</p>}
      <ul>
        {constraints.map((constraint, index) => (
          <li key={index} aria-label={t("constraint.item", { number: index + 1 })}>
            {constraint.kind === "forbidden" && <>{t("constraint.kinds.forbidden")} </>}
            {constraint.kind !== "finish_before" && (
              <Hour
                label={t(constraint.kind === "forbidden" ? "constraint.from" : "constraint.kinds.not_before")}
                value={constraint.start_hour}
                min={0}
                max={23}
                onChange={(start_hour) => set(index, { start_hour })}
              />
            )}{" "}
            {constraint.kind !== "not_before" && (
              <Hour
                label={t(constraint.kind === "forbidden" ? "constraint.to" : "constraint.kinds.finish_before")}
                value={constraint.end_hour}
                min={1}
                max={24}
                onChange={(end_hour) => set(index, { end_hour })}
              />
            )}{" "}
            <label>
              <input
                type="checkbox"
                checked={!constraint.hard}
                onChange={(event) => set(index, { hard: !event.target.checked })}
              />{" "}
              {t("constraint.soft")}
            </label>{" "}
            <button type="button" onClick={() => onChange(constraints.filter((_, i) => i !== index))}>
              {t("constraint.remove")}
            </button>
          </li>
        ))}
        <li>
          {CONSTRAINT_KINDS.map((kind) => (
            <button key={kind} type="button" onClick={() => onChange([...constraints, NEW[kind]])}>
              {t(`constraint.add.${kind}`)}
            </button>
          ))}
        </li>
      </ul>
    </fieldset>
  );
}
