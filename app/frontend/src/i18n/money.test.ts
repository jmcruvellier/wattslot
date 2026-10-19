import { describe, expect, it } from "vitest";

import { currencySymbol, formatMoney } from "./money";

const normal = (text: string) => text.replace(/\s/g, " ");

describe("formatMoney", () => {
  it("écrit le montant dans la langue et la devise de la maison", () => {
    expect(normal(formatMoney("fr", "EUR", 1.734))).toBe("1,73 €");
    expect(formatMoney("en", "USD", 1.734)).toBe("$1.73");
    expect(normal(formatMoney("de", "CHF", 0.2, { signed: true }))).toBe("+0,20 CHF");
    expect(normal(formatMoney("fr", "JPY", 1234.5))).toBe("1 235 JPY");
    expect(normal(formatMoney("fr", "EUR", 0.25, { digits: 2, maxDigits: 3 }))).toBe("0,25 €");
    expect(normal(formatMoney("fr", "EUR", 0.138252, { digits: 2, maxDigits: 3 }))).toBe("0,138 €");
  });

  it("donne le symbole de la devise", () => {
    expect(currencySymbol("fr", "EUR")).toBe("€");
    expect(currencySymbol("en", "GBP")).toBe("£");
  });
});
