// Aperçu des prix d'un tarif en cours de saisie (lot 4 de la refonte des tarifs) : une grille
// heure par heure, une ligne par jour des sept jours à venir, ou par sorte de jour annoncé
// (Tempo, EJP). Les prix viennent du serveur, qui les calcule comme pour le plan (jours fériés,
// plages à la minute, prix lus dans HA). Une seule teinte, du plus clair (le moins cher) au plus
// foncé ; la grille est un tableau, dont chaque case dit son heure et son prix.

import { useEffect, useMemo, useState } from "react";

import { postJson } from "../api";
import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import type { Tariff } from "./configuration";

interface PreviewRow {
  day: string; // AAAA-MM-JJ
  holiday: boolean;
  color: string | null;
  prices: number[]; // 24 prix, de 0 h à 23 h
}

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const MAX_LEGEND = 6; // au-delà (heures mixtes des plages à la minute), le minimum et le maximum

export default function TariffPreview({ tariff }: { tariff: Tariff }) {
  const { t, language } = useI18n();
  const { perKwh } = useCurrency();
  const [rows, setRows] = useState<PreviewRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [focus, setFocus] = useState<{ row: number; hour: number } | null>(null);
  const body = JSON.stringify(tariff);

  // Recalculé un instant après la dernière modification, pour ne pas interroger à chaque frappe.
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      postJson<{ rows: PreviewRow[] }>("api/configuration/tariff-preview", JSON.parse(body))
        .then((found) => {
          if (cancelled) return;
          setRows(found.rows);
          setFailed(false);
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [body]);

  const prices = useMemo(() => [...new Set((rows ?? []).flatMap((row) => row.prices))].sort((a, b) => a - b), [rows]);
  if (failed && rows === null) return <p role="status">{t("tariff.preview.failed")}</p>;
  if (rows === null || rows.length === 0) return null;

  const lowest = prices[0];
  const highest = prices[prices.length - 1];
  // Part de la teinte : 15 % pour le moins cher, 100 % pour le plus cher.
  const share = (price: number) => (highest === lowest ? 60 : Math.round(15 + (85 * (price - lowest)) / (highest - lowest)));
  const fill = (price: number) => `color-mix(in oklab, var(--grid-import) ${share(price)}%, var(--surface-alt))`;
  const label = (row: PreviewRow) => {
    if (row.color !== null) return t("tariff.color_named", { color: row.color });
    const name = new Date(`${row.day}T12:00:00`).toLocaleDateString(language, { weekday: "short", day: "numeric" });
    return row.holiday ? t("tariff.preview.holiday", { day: name }) : name;
  };
  const span = (hour: number) => t("tariff.preview.hours", { from: hour, to: hour + 1 });
  const legend = prices.length <= MAX_LEGEND ? prices : [lowest, highest];
  const focused = focus && rows[focus.row];

  return (
    <section className="tariff-preview" aria-label={t("tariff.preview.title")}>
      <p>
        <strong>{t(rows[0].color === null ? "tariff.preview.title" : "tariff.preview.title_days")}</strong>
      </p>
      <table className="tariff-grid" onMouseLeave={() => setFocus(null)}>
        <thead>
          <tr>
            <td className="tariff-grid-corner" />
            {HOURS.map((hour) => (
              <th key={hour} scope="col" aria-label={span(hour)}>
                {hour % 6 === 0 ? `${hour} h` : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.day}-${row.color ?? ""}`}>
              <th scope="row">{label(row)}</th>
              {row.prices.map((price, hour) => (
                <td
                  key={hour}
                  style={{ background: fill(price) }}
                  title={`${span(hour)} : ${perKwh(price)}`}
                  aria-label={`${span(hour)} : ${perKwh(price)}`}
                  onMouseEnter={() => setFocus({ row: index, hour })}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tariff-preview-readout" aria-live="polite">
        {focused
          ? `${label(focused)} · ${span(focus.hour)} : ${perKwh(focused.prices[focus.hour])}`
          : t("tariff.preview.hint")}
      </p>
      <ul className="tariff-preview-legend" aria-label={t("tariff.preview.legend")}>
        {legend.map((price) => (
          <li key={price}>
            <span className="tariff-preview-swatch" style={{ background: fill(price) }} /> {perKwh(price)}
          </li>
        ))}
      </ul>
    </section>
  );
}
