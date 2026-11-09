// Autres départs d'un appareil, proposés par le plan du jour : un bouton chacun, qui impose ce
// départ au calcul (/api/planning/choices) puis le relance ; un départ choisi se rend au calcul.
// Partagé par « Prochaine action » (Aujourd'hui) et « Pourquoi ce plan » (Planning, Aujourd'hui),
// et par la frise, qui propose aussi une heure libre, pour aujourd'hui comme pour demain ou un
// jour suivant (`day`).

import { useState } from "react";

import { deleteRequest, postJson } from "../api";
import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n/translate";
import Button from "../ui/Button";
import { clock } from "./format";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

export interface OtherStart {
  start_min: number;
  cost_eur_delta: number;
  import_kwh_delta: number;
}

export default function OtherStarts({
  device,
  alternatives,
  chosen,
  onChanged,
  day,
  freeFrom,
}: {
  device: string;
  alternatives: OtherStart[];
  chosen: boolean;
  onChanged: () => void;
  day?: string; // jour du plan (AAAA-MM-JJ) ; aucun : aujourd'hui
  freeFrom?: number; // heure libre proposée après cette minute ; aucune : pas d'heure libre
}) {
  const { language, t } = useI18n();
  const { money } = useCurrency();
  const [state, setState] = useState<"idle" | "running" | "failed">("idle");
  const [free, setFree] = useState<number | null>(null);
  const hours = freeFrom === undefined ? [] : HOURS.filter((h) => h * 60 > freeFrom);
  if (alternatives.length === 0 && !chosen && hours.length === 0) return null;
  const choose = (start_min: number) =>
    postJson("api/planning/choices", day ? { device, start_min, day } : { device, start_min });
  const freeHour = free !== null && hours.includes(free) ? free : (hours[0] ?? 0);
  const dayQuery = day ? `?day=${encodeURIComponent(day)}` : "";

  const run = async (change: () => Promise<unknown>) => {
    setState("running");
    try {
      await change();
      await postJson("api/planning/run", {}); // nouveau plan avec ce départ
      setState("idle");
      onChanged();
    } catch {
      setState("failed");
    }
  };

  return (
    <div className="other-starts">
      {/* Style de la ligne du créneau (« Entre … ») : le texte atténué (dim) devient illisible
       * sur certains thèmes. */}
      {alternatives.length > 0 && <p>{t("plan.choice.others")}</p>}
      <p className="other-starts-buttons">
        {alternatives.map((other) => {
          const time = clock(other.start_min, language);
          const cost = money(other.cost_eur_delta, { digits: 2, signed: true });
          const grid = formatNumber(language, other.import_kwh_delta, 1);
          return (
            <Button
              key={other.start_min}
              disabled={state === "running"}
              aria-label={t("plan.choice.choose", { time, cost, grid })}
              onClick={() => void run(() => choose(other.start_min))}
            >
              {time} · {cost}
            </Button>
          );
        })}
        {chosen && (
          /* Comme les autres boutons de la ligne : contour et icône, le texte seul du bouton
           * discret se perd sur certains thèmes. */
          <Button
            icon="refresh"
            disabled={state === "running"}
            onClick={() => void run(() => deleteRequest(`api/planning/choices/${encodeURIComponent(device)}${dayQuery}`))}
          >
            {t("plan.choice.revert")}
          </Button>
        )}
      </p>
      {hours.length > 0 && (
        <p className="other-starts-buttons">
          <label>
            {t("plan.choice.other_time")}{" "}
            <select value={freeHour} onChange={(event) => setFree(Number(event.target.value))}>
              {hours.map((h) => (
                <option key={h} value={h}>
                  {clock(h * 60, language)}
                </option>
              ))}
            </select>
          </label>{" "}
          <Button disabled={state === "running"} onClick={() => void run(() => choose(freeHour * 60))}>
            {t("plan.choice.start_at", { time: clock(freeHour * 60, language) })}
          </Button>
        </p>
      )}
      {state === "running" && <p role="status">{t("plan.choice.running")}</p>}
      {state === "failed" && <p role="alert">{t("plan.choice.failed")}</p>}
    </div>
  );
}
