// Thèmes (lot 6b.1) : mêmes variables partout, Graphite identique dans son bloc et dans la règle
// du mode automatique, contrastes AA (4,5:1) des textes, script d'index.html d'accord avec la
// liste des thèmes.

import { describe, expect, it } from "vitest";

import indexHtml from "../../index.html?raw";
import css from "./themes.css?raw";
import { THEMES } from "./theme";

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`bloc introuvable : ${selector}`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries(
    [...body.matchAll(/(--[a-z-]+):\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]),
  );
}

const PALETTES: Record<string, Record<string, string>> = {
  ivory: block('[data-theme="ivory"]'),
  graphite: block('[data-theme="graphite"]'),
  ocean: block('[data-theme="ocean"]'),
  meadow: block('[data-theme="meadow"]'),
  dusk: block('[data-theme="dusk"]'),
};
const AUTO_DARK = block('[data-theme="auto"]');

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

// Textes et fonds sur lesquels ils s'affichent.
const PAIRS: [string, string][] = [
  ["--text", "--bg"],
  ["--text", "--surface"],
  ["--text", "--surface-alt"],
  ["--text-dim", "--bg"],
  ["--text-dim", "--surface"],
  ["--text-dim", "--surface-alt"],
  ["--accent-text", "--accent"],
  ["--link", "--bg"],
  ["--link", "--surface"],
  ["--danger", "--surface"],
  ["--ok", "--surface"],
  ["--warning", "--surface"],
];

describe("thèmes", () => {
  it("couvre chaque thème du choix, sauf Automatique", () => {
    expect(Object.keys(PALETTES)).toEqual(THEMES.filter((theme) => theme !== "auto"));
  });

  it("donne les mêmes variables à chaque thème, en couleurs hexadécimales", () => {
    const names = Object.keys(PALETTES.ivory).sort();
    for (const palette of Object.values(PALETTES)) {
      expect(Object.keys(palette).sort()).toEqual(names);
      for (const value of Object.values(palette)) expect(value).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("prend Ivoire en automatique, et Graphite tel quel quand le système est en sombre", () => {
    expect(css.replace(/\r/g, "")).toContain(':root,\n:root[data-theme="auto"],\n[data-theme="ivory"] {');
    // Seul le bloc de la règle @media se termine par data-theme="auto".
    expect(css.indexOf(':root[data-theme="auto"] {')).toBeGreaterThan(css.indexOf("@media (prefers-color-scheme: dark)"));
    expect(AUTO_DARK).toEqual(PALETTES.graphite);
  });

  it.each(Object.entries(PALETTES))("tient les contrastes AA : %s", (_, palette) => {
    for (const [text, background] of PAIRS) {
      expect(contrast(palette[text], palette[background]), `${text} sur ${background}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("applique avant le premier affichage les mêmes thèmes que le choix", () => {
    const listed = /\[("[a-z]+"(?:, "[a-z]+")*)\]\.indexOf\(theme\)/.exec(indexHtml)?.[1];
    expect(listed?.split(", ").map((name) => name.replaceAll('"', ""))).toEqual(
      THEMES.filter((theme) => theme !== "auto"),
    );
    expect(indexHtml).toContain('"wattslot.theme"');
  });

  it("déclare le favicon de WattSlot par une adresse relative (ingress)", () => {
    expect(indexHtml).toContain('<link rel="icon" type="image/svg+xml" href="favicon.svg" />');
  });

  it("reprend une fois les réglages gardés sous l'ancien nom energy-optimizer (lot 7.1)", () => {
    const script = /<script>([\s\S]*?)<\/script>/.exec(indexHtml)?.[1] ?? "";
    window.localStorage.clear();
    window.localStorage.setItem("energy-optimizer.theme", "ocean");
    window.localStorage.setItem("energy-optimizer.language", "de");
    window.localStorage.setItem("wattslot.menu", "open");
    window.localStorage.setItem("energy-optimizer.menu", "collapsed");

    new Function(script)();

    expect(window.localStorage.getItem("wattslot.theme")).toBe("ocean");
    expect(window.localStorage.getItem("wattslot.language")).toBe("de");
    expect(window.localStorage.getItem("wattslot.menu")).toBe("open"); // le nouveau l'emporte
    expect(window.localStorage.getItem("energy-optimizer.theme")).toBeNull();
    expect(document.documentElement.getAttribute("data-theme")).toBe("ocean");
    window.localStorage.clear();
    document.documentElement.setAttribute("data-theme", "auto");
  });
});
