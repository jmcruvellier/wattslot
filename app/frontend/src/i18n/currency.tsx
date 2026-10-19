// Devise de la maison (lot 7.3) : celle des prix saisis et des coûts. Réglage du serveur
// (api/settings/currency), sinon la devise de Home Assistant, sinon l'euro. Les montants sont mis
// en forme par Intl.NumberFormat, dans la langue de l'interface ; aucune conversion.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { getJson, putJson } from "../api";
import { useI18n } from "./I18nProvider";
import { currencySymbol, DEFAULT_CURRENCY, formatMoney, type CurrencyState } from "./money";

interface CurrencyValue {
  state: CurrencyState | null; // null : pas encore lu (ou illisible), euro en attendant
  save: (code: string | null) => Promise<void>;
}

const CurrencyContext = createContext<CurrencyValue | null>(null);

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CurrencyState | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getJson<CurrencyState>("api/settings/currency", controller.signal)
      .then(setState)
      .catch(() => undefined); // euro en attendant
    return () => controller.abort();
  }, []);

  const save = useCallback(async (code: string | null) => {
    setState(await putJson<CurrencyState>("api/settings/currency", { code }));
  }, []);

  const value = useMemo(() => ({ state, save }), [state, save]);
  return <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCurrency() {
  const { language } = useI18n();
  const context = useContext(CurrencyContext);
  const code = context?.state?.effective ?? DEFAULT_CURRENCY;
  return useMemo(
    () => ({
      code,
      state: context?.state ?? null,
      save: context?.save ?? (async () => undefined),
      symbol: currencySymbol(language, code),
      money: (value: number, options?: { digits?: number; maxDigits?: number; signed?: boolean }) =>
        formatMoney(language, code, value, options),
      /** Prix du kWh, deux ou trois décimales : « 0,25 €/kWh », « 0,138 €/kWh ». */
      perKwh: (value: number) => `${formatMoney(language, code, value, { digits: 2, maxDigits: 3 })}/kWh`,
    }),
    [code, context, language],
  );
}
