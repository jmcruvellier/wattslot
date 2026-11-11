// Qualité des prévisions d'une vue de jour, en pastille au coin du bloc « Indicateurs du plan » :
// libellé court (« Fiable », « Moyenne », « Incertaine ») pour tenir sur la ligne du titre,
// même sur téléphone ; d'après les données dont disposait le calcul (serveur :
// planning/forecast_quality.py). Un clic ouvre le détail : chaque critère, son niveau et sa raison.

import { useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import Sheet from "../ui/Sheet";
import type { ForecastQuality, QualityFactor, QualityLevel } from "./types";

const TONE: Record<QualityLevel, string> = {
  good: "trend-good",
  fair: "badge-medium",
  poor: "trend-bad",
};

const MARK: Record<QualityLevel, string> = { good: "●", fair: "◐", poor: "○" };

/** Texte d'un critère, avec sa précision éventuelle (heures sans relevés, régularité). */
function factorText(factor: QualityFactor, t: (key: string, params?: Record<string, string | number>) => string): string[] {
  const p = factor.params;
  const base = "plan.quality.factors";
  switch (factor.code) {
    case "consumption_history": {
      const days = Number(p.days ?? 0);
      const missing = Number(p.missing_hours ?? 0);
      const lines = [
        days === 0
          ? t(`${base}.consumption_history.none`)
          : t(`${base}.consumption_history.${p.same_weekday ? "same" : "all"}`, { days, target: Number(p.target ?? 6) }),
      ];
      if (days > 0 && missing > 0) lines.push(t(`${base}.consumption_history.missing`, { hours: missing }));
      return lines;
    }
    case "consumption_regularity":
      return [
        t(`${base}.consumption_regularity.text`, { percent: Number(p.percent ?? 0) }),
        t(`${base}.consumption_regularity.${factor.level}`),
      ];
    case "solar_source":
      return [t(`${base}.solar_source.${p.fallback ? "fallback" : "dedicated"}`)];
    case "weather_horizon": {
      const days = Number(p.days ?? 0);
      if (days <= 0) return [t(`${base}.weather_horizon.today`)];
      if (days === 1) return [t(`${base}.weather_horizon.tomorrow`)];
      return [t(`${base}.weather_horizon.${factor.level === "poor" ? "far" : "later"}`, { days })];
    }
    case "cycle_profiles":
      return [
        factor.level === "good"
          ? t(`${base}.cycle_profiles.good`)
          : t(`${base}.cycle_profiles.missing`, { devices: String(p.devices ?? "") }),
      ];
    case "history_import":
      return [t(`${base}.history_import`)];
  }
}

export function QualityBadge({ quality }: { quality: ForecastQuality }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const badge = t(`plan.quality.badge.${quality.level}`);
  return (
    <>
      <button
        type="button"
        className={`quality-pill ${TONE[quality.level]}`}
        aria-haspopup="dialog"
        aria-label={t("plan.quality.open", { badge })}
        onClick={() => setOpen(true)}
      >
        {MARK[quality.level]} {badge}
      </button>
      <Sheet open={open} title={t("plan.quality.title")} onClose={() => setOpen(false)}>
        <p>
          <span className={`trend trend-pill ${TONE[quality.level]}`}>
            {MARK[quality.level]} {badge}
          </span>{" "}
          <span className="dim">{t("plan.quality.score", { score: quality.score })}</span>
        </p>
        <p>{t(`plan.quality.summary.${quality.level}`)}</p>
        <ul className="quality-factors">
          {quality.factors.map((factor) => (
            <li key={factor.code}>
              <span className={`quality-mark ${TONE[factor.level]}`} role="img" aria-label={t(`plan.quality.levels.${factor.level}`)}>
                {MARK[factor.level]}
              </span>
              <span>
                {factorText(factor, t).map((line) => (
                  <span key={line} className="quality-line">
                    {line}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
        <p className="dim">{t("plan.quality.how")}</p>
      </Sheet>
    </>
  );
}
