// Autres départs d'un appareil, proposés par le plan du jour : un bouton chacun, qui impose ce
// départ au calcul (/api/planning/choices) puis le relance ; un départ choisi se rend au calcul.
// Partagé par « Prochaine action » (Aujourd'hui) et « Pourquoi ce plan » (Planning, Aujourd'hui).

import { useState } from "react";

import { deleteRequest, postJson } from "../api";
import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n/translate";
import Button from "../ui/Button";
import { clock } from "./format";

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
}: {
  device: string;
  alternatives: OtherStart[];
  chosen: boolean;
  onChanged: () => void;
}) {
  const { language, t } = useI18n();
  const { money } = useCurrency();
  const [state, setState] = useState<"idle" | "running" | "failed">("idle");
  if (alternatives.length === 0 && !chosen) return null;

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
      {alternatives.length > 0 && <p className="dim">{t("plan.choice.others")}</p>}
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
              onClick={() =>
                void run(() => postJson("api/planning/choices", { device, start_min: other.start_min }))
              }
            >
              {time} · {cost}
            </Button>
          );
        })}
        {chosen && (
          <Button
            variant="quiet"
            disabled={state === "running"}
            onClick={() => void run(() => deleteRequest(`api/planning/choices/${encodeURIComponent(device)}`))}
          >
            {t("plan.choice.revert")}
          </Button>
        )}
      </p>
      {state === "running" && <p role="status">{t("plan.choice.running")}</p>}
      {state === "failed" && <p role="alert">{t("plan.choice.failed")}</p>}
    </div>
  );
}
