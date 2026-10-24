// Phrases de « Ma maison en bref » (lot 6b.5), rédigées à partir de la configuration.

import type { Language } from "../i18n/translate";
import { DEFAULT_CURRENCY, formatMoney } from "../i18n/money";
import { formatNumber } from "../i18n/translate";
import {
  DEFAULT_PRICE_EUR_KWH,
  DEFAULT_RUNTIME,
  SEASONS,
  type DeviceSettings,
  type PriceBand,
  type Tariff,
  type TimeConstraint,
} from "./configuration";

export type T = (key: string, params?: Record<string, string | number>) => string;

export const PLACED = new Set(["CycleBehavior", "EnergyByDeadlineBehavior", "RuntimeBehavior"]);
const DIRECTIONS = ["north", "north_east", "east", "south_east", "south", "south_west", "west", "north_west"] as const;
const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];

const hours = (value: number) => `${value} h`;
const bandTime = (value: number) => {
  const minute = value % 60;
  return `${hours(Math.floor(value / 60))}${minute ? ` ${String(minute).padStart(2, "0")}` : ""}`;
};

/** Bornes en minutes des plages les moins chères, réunies à minuit. */
export function cheapestRanges(bands: PriceBand[]): [number, number][] {
  if (bands.length === 0) return [];
  const lowest = Math.min(...bands.map((band) => band.eur_kwh));
  const ranges = bands
    .filter((band) => band.eur_kwh === lowest)
    .map((band): [number, number] => [band.start_hour * 60 + (band.start_minute ?? 0), band.end_hour * 60 + (band.end_minute ?? 0)])
    .sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && last[1] === range[0]) last[1] = range[1];
    else merged.push([...range]);
  }
  // 0 h – 6 h et 22 h – 24 h : une seule plage de nuit.
  if (merged.length > 1 && merged[0][0] === 0 && merged[merged.length - 1][1] === 24 * 60) {
    const night = merged.pop()!;
    merged[0] = [night[0], merged[0][1]];
  }
  return merged;
}

export function tariffText(
  tariff: Tariff | null | undefined,
  t: T,
  language: Language,
  currency: string = DEFAULT_CURRENCY,
): string {
  const price = (value: number) => `${formatMoney(language, currency, value)}/kWh`;
  if (!tariff) return t("home_summary.contract.single", { price: price(DEFAULT_PRICE_EUR_KWH) });
  switch (tariff.kind) {
    case "SingleTariff":
      return t("home_summary.contract.single", { price: price(tariff.base_eur_kwh) });
    case "TimeOfUseTariff": {
      const ranges = cheapestRanges(tariff.bands);
      if (ranges.length === 0) return t("home_summary.contract.single", { price: price(tariff.base_eur_kwh) });
      return t("home_summary.contract.off_peak", {
        ranges: ranges.map(([start, end]) => `${bandTime(start)} – ${bandTime(end)}`).join(", "),
      });
    }
    case "DayColorTariff":
      return t("home_summary.contract.colors");
    case "DynamicTariff":
      return t("home_summary.contract.dynamic");
  }
}

export function direction(azimuth: number): (typeof DIRECTIONS)[number] {
  return DIRECTIONS[Math.round((((azimuth % 360) + 360) % 360) / 45) % 8];
}

export function list(items: string[], t: T): string {
  if (items.length <= 1) return items.join("");
  return t("home_summary.and", { items: items.slice(0, -1).join(", "), last: items[items.length - 1] });
}

function recurrenceText(rule: string, t: T, language: Language): string {
  const parts = Object.fromEntries(rule.split(";").map((part) => part.split("=") as [string, string]));
  const interval = Number(parts.INTERVAL ?? 1);
  if (parts.FREQ === "DAILY") return interval > 1 ? t("home_summary.every_days", { count: interval }) : t("home_summary.daily");
  if (parts.FREQ === "WEEKLY") {
    // Lundi 5 janvier 2026 : noms des jours dans la langue de l'interface.
    const names = (parts.BYDAY ?? "")
      .split(",")
      .filter((day: string) => WEEKDAYS.includes(day))
      .map((day: string) => new Date(2026, 0, 5 + WEEKDAYS.indexOf(day)).toLocaleDateString(language, { weekday: "long" }));
    const days = names.length ? list(names, t) : null;
    if (interval > 1) return t("home_summary.every_weeks", { count: interval, days: days ?? "" }).replace(/,\s*$/, "");
    return days ? t("home_summary.weekly_on", { days }) : t("home_summary.weekly");
  }
  return t("home_summary.recurring");
}

function constraintText(constraint: TimeConstraint, t: T): string {
  return t(`home_summary.constraint.${constraint.kind}`, {
    start: hours(constraint.start_hour),
    end: hours(constraint.end_hour),
  });
}

/** Phrase d'un appareil placé par le calcul. */
export function deviceText(settings: DeviceSettings, names: Map<string, string>, t: T, language: Language): string {
  const parts: string[] = [];
  if (settings.behavior === "CycleBehavior") {
    if (settings.after) parts.push(t("home_summary.after", { device: names.get(settings.after) ?? settings.after }));
    else if (settings.recurrence) parts.push(recurrenceText(settings.recurrence.rule, t, language));
    else parts.push(t("home_summary.on_request"));
  } else if (settings.behavior === "EnergyByDeadlineBehavior") {
    if (settings.energy) {
      parts.push(
        t(settings.energy.daily ? "home_summary.energy_daily" : "home_summary.energy_requested", {
          kwh: formatNumber(language, settings.energy.energy_kwh),
          deadline: hours(settings.energy.deadline_hour),
        }),
      );
    } else {
      parts.push(t("home_summary.on_request"));
    }
  } else {
    const runtime = settings.runtime ?? DEFAULT_RUNTIME;
    parts.push(
      list(
        SEASONS.map((season) => {
          const value = runtime.minimum_hours[season] ?? 0;
          return value > 0
            ? t(`home_summary.season.${season}`, { hours: formatNumber(language, value) })
            : t(`home_summary.season_none.${season}`);
        }),
        t,
      ),
    );
  }
  for (const constraint of settings.constraints ?? []) parts.push(constraintText(constraint, t));
  const text = parts.join(" · ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
