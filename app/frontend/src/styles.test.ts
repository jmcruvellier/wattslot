// Alignement des blocs de chaque écran : la colonne de 90rem est centrée par le remplissage de
// main, et aucun bloc ne la décale par une marge latérale. Avant, `main > *` centrait chaque bloc
// par des marges automatiques qu'une règle de bloc (`margin: 0.75rem 0`) écrasait.
import { describe, expect, it } from "vitest";

import css from "./styles.css?raw";

type Rule = { selectors: string[]; declarations: Map<string, string> };

// Règles les plus internes (les @media sont aplaties) ; les commentaires sont retirés.
function parseRules(source: string): Rule[] {
  const text = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: Rule[] = [];
  for (const match of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const declarations = new Map<string, string>();
    for (const part of match[2].split(";")) {
      const colon = part.indexOf(":");
      if (colon < 0) continue;
      declarations.set(part.slice(0, colon).trim(), part.slice(colon + 1).trim());
    }
    rules.push({ selectors: match[1].split(",").map((s) => s.trim()), declarations });
  }
  return rules;
}

// Marges gauche et droite posées par une règle (vide si elle n'en pose pas).
function inlineMargins(declarations: Map<string, string>): string[] {
  const values: string[] = [];
  const margin = declarations.get("margin");
  if (margin) {
    const parts = margin.replace(/!important/, "").trim().split(/\s+/);
    values.push(parts[1] ?? parts[0], parts[3] ?? parts[1] ?? parts[0]);
  }
  for (const property of ["margin-inline", "margin-left", "margin-right", "margin-inline-start", "margin-inline-end"]) {
    const value = declarations.get(property);
    if (value) values.push(...value.replace(/!important/, "").trim().split(/\s+/));
  }
  return values;
}

const rules = parseRules(css);

// Blocs posés directement dans main ou dans la section d'un écran.
const BLOCKS = [
  "plan-more",
  "home-details",
  "agenda",
  "week-agenda",
  "plan-agenda",
  "state-message",
  "onboarding",
  "setup-card",
  "home-summary",
  "settings-home",
  "more-links",
  "today",
  "assistant",
  "top-bar",
];

describe("alignement des blocs", () => {
  it("centre la colonne par le remplissage de main", () => {
    const main = rules.filter((rule) => rule.selectors.includes("main"));
    expect(main[0].declarations.get("padding-inline")).toBe("max(var(--main-gutter), (100% - 90rem) / 2)");
    // Aucune règle main ne repose un remplissage latéral fixe par-dessus.
    for (const rule of main.slice(1)) {
      expect(rule.declarations.has("padding")).toBe(false);
      expect(rule.declarations.has("padding-inline")).toBe(false);
    }
  });

  it("ne centre plus les blocs par des marges", () => {
    const children = rules.filter((rule) => rule.selectors.some((s) => /^main\s*>/.test(s)));
    for (const rule of children) expect(inlineMargins(rule.declarations)).toEqual([]);
  });

  it.each(BLOCKS)("ne pose pas de marge latérale sur .%s", (block) => {
    const own = rules.filter((rule) => rule.selectors.some((s) => new RegExp(`\\.${block}$`).test(s)));
    for (const rule of own) {
      for (const value of inlineMargins(rule.declarations)) expect(value).toBe("0");
    }
  });
});
