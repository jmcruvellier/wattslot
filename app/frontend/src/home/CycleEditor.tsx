// Règles d'un cycle à démarrer (lot 3.5) : récurrence (tous les N jours depuis le dernier cycle,
// ou certains jours de la semaine), démarre après la fin du cycle d'un autre équipement (le même
// jour), tolérance de report d'une tâche en attente.

import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import type { Recurrence } from "./configuration";

export const DEFAULT_DELAY_DAYS = 2; // backend : planning/assignment.MAX_DELAY_DAYS
const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"] as const;

type Mode = "none" | "daily" | "weekly" | "custom";

// Lecture d'une règle RFC 5545 pour le formulaire ; une autre règle reste éditable en texte.
function readRule(recurrence: Recurrence | null): { mode: Mode; interval: number; days: string[] } {
  if (recurrence === null) return { mode: "none", interval: 2, days: [] };
  const daily = /^FREQ=DAILY(?:;INTERVAL=(\d+))?$/.exec(recurrence.rule);
  if (daily) return { mode: "daily", interval: Number(daily[1] ?? 1), days: [] };
  const weekly = /^FREQ=WEEKLY;BYDAY=([A-Z,]+)$/.exec(recurrence.rule);
  if (weekly) return { mode: "weekly", interval: 1, days: weekly[1].split(",") };
  return { mode: "custom", interval: 1, days: [] };
}

const dailyRule = (interval: number) => (interval > 1 ? `FREQ=DAILY;INTERVAL=${interval}` : "FREQ=DAILY");
const weeklyRule = (days: string[]) =>
  `FREQ=WEEKLY;BYDAY=${WEEKDAYS.filter((d) => days.includes(d)).join(",") || "MO"}`;

export default function CycleEditor({ after, maxDelayDays, recurrence, name, others, onChange }: {
  after: string | null;
  maxDelayDays: number | null;
  recurrence: Recurrence | null;
  name: string; // nom de l'équipement, pour les noms accessibles
  others: { key: string; name: string }[]; // autres équipements à cycles
  onChange: (change: {
    after?: string | null;
    max_delay_days?: number | null;
    recurrence?: Recurrence | null;
  }) => void;
}) {
  const { t } = useI18n();
  const current = readRule(recurrence);
  const setRule = (rule: string) => onChange({ recurrence: { ...(recurrence ?? {}), rule } });
  const setMode = (mode: Mode) => {
    if (mode === "none") onChange({ recurrence: null });
    else if (mode === "daily") setRule(dailyRule(current.interval));
    else if (mode === "weekly") setRule(weeklyRule(current.days));
    else setRule(recurrence?.rule ?? "FREQ=DAILY");
  };

  return (
    <fieldset aria-label={t("cycle.title", { device: name })}>
      <legend>{t("cycle.title", { device: name })}</legend>
      <p>
        <label>
          {t("cycle.after")}{" "}
          <select value={after ?? ""} onChange={(event) => onChange({ after: event.target.value || null })}>
            <option value="">{t("cycle.no_after")}</option>
            {others.map((other) => (
              <option key={other.key} value={other.key}>
                {other.name}
              </option>
            ))}
          </select>
        </label>
        <Hint text={t("cycle.after_hint")} />
      </p>
      <Advanced modified={recurrence !== null || maxDelayDays !== null}>
      <p>
        <label>
          {t("cycle.recurrence")}{" "}
          <select value={current.mode} onChange={(event) => setMode(event.target.value as Mode)}>
            {(["none", "daily", "weekly", "custom"] as const).map((mode) => (
              <option key={mode} value={mode}>
                {t(`cycle.modes.${mode}`)}
              </option>
            ))}
          </select>
        </label>{" "}
        {current.mode === "daily" && (
          <label>
            {t("cycle.every")}{" "}
            <input
              type="number"
              min="1"
              step="1"
              value={current.interval}
              onChange={(event) => setRule(dailyRule(Math.max(1, Number(event.target.value) || 1)))}
            />{" "}
            {t("cycle.days_since")}
          </label>
        )}
        {current.mode === "weekly" &&
          WEEKDAYS.map((day) => (
            <label key={day}>
              <input
                type="checkbox"
                checked={current.days.includes(day)}
                onChange={(event) =>
                  setRule(weeklyRule(event.target.checked ? [...current.days, day] : current.days.filter((d) => d !== day)))
                }
              />{" "}
              {t(`cycle.weekdays.${day}`)}{" "}
            </label>
          ))}
        {current.mode === "custom" && (
          <label>
            {t("cycle.rule")}{" "}
            <input value={recurrence?.rule ?? ""} onChange={(event) => setRule(event.target.value)} />
          </label>
        )}
      </p>
      {current.mode !== "none" && <p>{t("cycle.replaces_tasks")}</p>}
      <p>
        <label>
          {t("cycle.delay")}{" "}
          <input
            type="number"
            min="0"
            max="14"
            step="1"
            placeholder={String(DEFAULT_DELAY_DAYS)}
            value={maxDelayDays ?? ""}
            onChange={(event) =>
              onChange({ max_delay_days: event.target.value === "" ? null : Number(event.target.value) })
            }
          />{" "}
          {t("cycle.days")}
        </label>
      </p>
      </Advanced>
    </fieldset>
  );
}
