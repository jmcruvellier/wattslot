import { describe, expect, it } from "vitest";

import { catalogOf, detectLanguage, formatNumber, LANGUAGES, reviewed, translate, type Catalog } from "./translate";

const PARAM = /\{(\w+)\}/g;

function entries(catalog: Catalog, prefix = ""): Map<string, string> {
  const result = new Map<string, string>();
  for (const [key, value] of Object.entries(catalog)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") result.set(path, value);
    else for (const [k, v] of entries(value, path)) result.set(k, v);
  }
  return result;
}

function params(text: string): string[] {
  return [...text.matchAll(PARAM)].map((match) => match[1]).sort();
}

describe("catalogues", () => {
  const emptyBand = {
    en: "Tariff: band {band} is empty (start and end have the same hour and minute).",
    fr: "Tarif : la plage {band} est vide (début et fin à la même heure et à la même minute).",
    de: "Tarif: Zeitfenster {band} ist leer (Beginn und Ende haben dieselbe Stunde und Minute).",
    es: "Tarifa: la franja {band} está vacía (inicio y fin tienen la misma hora y el mismo minuto).",
    it: "Tariffa: la fascia {band} è vuota (inizio e fine hanno la stessa ora e lo stesso minuto).",
    nl: "Tarief: tijdvak {band} is leeg (begin en einde hebben hetzelfde uur en dezelfde minuut).",
  };

  it.each(LANGUAGES)("%s décrit une plage vide par l'égalité des heures et minutes, pas par le passage de minuit", async (language) => {
    expect(entries(await catalogOf(language)).get("configuration.issue.band_empty")).toBe(emptyBand[language]);
  });

  for (const language of LANGUAGES) {
    it(`${language} a les mêmes clés et les mêmes paramètres que l'anglais`, async () => {
      const reference = entries(await catalogOf("en"));
      const current = entries(await catalogOf(language));
      expect([...current.keys()].sort()).toEqual([...reference.keys()].sort());
      for (const [key, text] of reference) {
        expect(params(current.get(key) ?? ""), key).toEqual(params(text));
      }
    });

    it(`${language} dit s'il est relu, comme la liste des langues à relire`, async () => {
      const status = (await catalogOf(language))._meta as Catalog;
      expect(status.status).toBe(reviewed(language) ? "reviewed" : "to_review");
    });
  }
});

describe("nombres", () => {
  it("au format de chaque langue, sans séparateur de milliers", () => {
    expect(formatNumber("fr", 1.5, 2)).toBe("1,50");
    expect(formatNumber("en", 1.5, 2)).toBe("1.50");
    expect(formatNumber("de", 2026)).toBe("2026");
    expect(translate("fr", "plan.series.floor", { pct: 12.5 })).toBe("Plancher 12,5 %");
  });
});

describe("translate", () => {
  it("remplace les paramètres", () => {
    expect(translate("fr", "health.version", { version: "1.2.3" })).toBe("Version 1.2.3");
  });

  it("rend la clé quand elle n'existe dans aucun catalogue", () => {
    expect(translate("fr", "inconnue.cle")).toBe("inconnue.cle");
  });
});

describe("detectLanguage", () => {
  it("préfère ?lang= dans l'URL", () => {
    expect(detectLanguage("?lang=fr", "en", ["en-US"])).toBe("fr");
  });

  it("prend ensuite le choix mémorisé", () => {
    expect(detectLanguage("", "fr", ["en-US"])).toBe("fr");
  });

  it("prend ensuite la première langue du navigateur prise en charge", () => {
    expect(detectLanguage("", null, ["ja-JP", "fr-FR", "en"])).toBe("fr");
  });

  it("se replie sur l'anglais", () => {
    expect(detectLanguage("?lang=xx", "yy", ["ja"])).toBe("en");
  });
});
