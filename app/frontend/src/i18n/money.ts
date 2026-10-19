// Mise en forme des montants dans la devise de la maison (lot 7.3), par Intl.NumberFormat.

import type { Language } from "./translate";

export interface CurrencyState {
  code: string | null; // réglage ; null : suivre Home Assistant
  home_assistant: string | null;
  effective: string;
  choices: string[];
}

export const DEFAULT_CURRENCY = "EUR";

/** Montant dans la langue et la devise : « 1,73 € », « $1.73 », « 1,73 CHF ». */
export function formatMoney(
  language: Language,
  code: string,
  value: number,
  options: { digits?: number; maxDigits?: number; signed?: boolean } = {},
): string {
  return new Intl.NumberFormat(language, {
    style: "currency",
    currency: code,
    ...(options.digits !== undefined && {
      minimumFractionDigits: options.digits,
      maximumFractionDigits: Math.max(options.digits, options.maxDigits ?? options.digits),
    }),
    ...(options.signed && { signDisplay: "exceptZero" }),
  }).format(value);
}

/** Symbole de la devise dans la langue : « € », « $ », « CHF ». */
export function currencySymbol(language: Language, code: string): string {
  const parts = new Intl.NumberFormat(language, { style: "currency", currency: code }).formatToParts(0);
  return parts.find((part) => part.type === "currency")?.value ?? code;
}
