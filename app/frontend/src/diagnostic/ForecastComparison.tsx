// Prévision Open-Meteo des 7 derniers jours comparée à la production mesurée (lot 4.4) : montre
// l'écart d'une prévision calculée d'après les panneaux, pour inviter à installer une vraie
// intégration de prévision ou à corriger la description des panneaux.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "./format";

export interface Comparison {
  available: boolean;
  reason: "no_panels" | "no_position" | "unavailable" | null;
  days: { day: string; forecast_kwh: number; measured_kwh: number | null }[];
  ratio: number | null; // production mesurée / prévue
}

type Load = { status: "loading" } | { status: "ready"; comparison: Comparison } | { status: "error" };

export default function ForecastComparison() {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getJson<Comparison>("api/forecast/comparison", controller.signal)
      .then((comparison) => setLoad({ status: "ready", comparison }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, []);

  const kwh = (value: number) => formatNumber(language, value, 1);

  return (
    <section aria-labelledby="forecast-comparison">
      <h3 id="forecast-comparison">{t("forecast_comparison.title")}</h3>
      {load.status === "loading" && <p>{t("forecast_comparison.loading")}</p>}
      {load.status === "error" && <p role="alert">{t("forecast_comparison.error")}</p>}
      {load.status === "ready" && !load.comparison.available && (
        <p>{t(`forecast_comparison.reason.${load.comparison.reason ?? "unavailable"}`)}</p>
      )}
      {load.status === "ready" && load.comparison.available && (
        <>
          <p>{t("forecast_comparison.intro")}</p>
          <table>
            <thead>
              <tr>
                <th scope="col">{t("forecast_comparison.day")}</th>
                <th scope="col">{t("forecast_comparison.forecast")}</th>
                <th scope="col">{t("forecast_comparison.measured")}</th>
              </tr>
            </thead>
            <tbody>
              {load.comparison.days.map((day) => (
                <tr key={day.day}>
                  <th scope="row">
                    {new Date(`${day.day}T12:00:00`).toLocaleDateString(language, {
                      weekday: "short",
                      day: "numeric",
                      month: "short",
                    })}
                  </th>
                  <td>{kwh(day.forecast_kwh)} kWh</td>
                  <td>{day.measured_kwh === null ? "—" : `${kwh(day.measured_kwh)} kWh`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            {load.comparison.ratio === null
              ? t("forecast_comparison.no_ratio")
              : t("forecast_comparison.ratio", {
                  percent: formatNumber(language, load.comparison.ratio * 100, 0),
                })}
          </p>
        </>
      )}
    </section>
  );
}
