// Traductions de l'interface : un catalogue JSON par langue, mêmes clés et mêmes
// paramètres `{nom}` dans tous les catalogues (vérifié par translate.test.ts). Tous sont chargés
// à la demande (lot 5.7 pour les quatre dernières langues, puis le français et l'anglais pour
// libérer le fichier principal) : la langue de l'interface avant le premier affichage
// (`main.tsx`), l'anglais (langue de secours) à côté. Chaque catalogue dit s'il a été relu
// (`_meta.status`).

export type Catalog = { [key: string]: string | Catalog };

export const LANGUAGES = ["fr", "en", "de", "nl", "es", "it"] as const;

export type Language = (typeof LANGUAGES)[number];

export const SUPPORTED_LANGUAGES: Language[] = [...LANGUAGES];

export const FALLBACK_LANGUAGE: Language = "en";

/** Nom de chaque langue dans sa langue, pour le choix de la langue. */
export const LANGUAGE_NAMES: Record<Language, string> = {
  fr: "Français",
  en: "English",
  de: "Deutsch",
  nl: "Nederlands",
  es: "Español",
  it: "Italiano",
};

// Catalogues chargés.
const CATALOGS: Partial<Record<Language, Catalog>> = {};

const LOADERS: Record<Language, () => Promise<{ default: Catalog }>> = {
  fr: () => import("./catalogs/fr.json"),
  en: () => import("./catalogs/en.json"),
  de: () => import("./catalogs/de.json"),
  nl: () => import("./catalogs/nl.json"),
  es: () => import("./catalogs/es.json"),
  it: () => import("./catalogs/it.json"),
};

export function isLoaded(language: Language): boolean {
  return language in CATALOGS;
}

/** Charge le catalogue d'une langue (sans effet s'il l'est déjà). */
export async function loadCatalog(language: Language): Promise<void> {
  if (isLoaded(language)) return;
  CATALOGS[language] = (await LOADERS[language]()).default;
}

/** Catalogue d'une langue, chargé s'il le faut (tests de la CI). */
export async function catalogOf(language: Language): Promise<Catalog> {
  await loadCatalog(language);
  return CATALOGS[language]!;
}

// Langues préparées puis relues par un natif : retirer la langue d'ici une fois relue (et
// passer `_meta.status` de son catalogue à « reviewed »).
const TO_REVIEW: readonly Language[] = ["de", "nl", "es", "it"];

/** Catalogue relu par un natif, ou préparé et « à relire » (sans avoir à le charger). */
export function reviewed(language: Language): boolean {
  return !TO_REVIEW.includes(language);
}

export type Params = Record<string, string | number>;

// Choix de la langue gardé dans le navigateur.
export const STORAGE_KEY = "wattslot.language";

export function readStoredLanguage(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function isLanguage(value: string | null | undefined): value is Language {
  return value != null && (LANGUAGES as readonly string[]).includes(value);
}

function lookup(catalog: Catalog, key: string): string | undefined {
  let node: string | Catalog | undefined = catalog;
  for (const part of key.split(".")) {
    if (node === undefined || typeof node === "string") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/** Nombre au format de la langue (virgule décimale en français…), sans séparateur de milliers
 * (années, minutes). */
export function formatNumber(language: Language, value: number, decimals?: number): string {
  return new Intl.NumberFormat(language, {
    useGrouping: false,
    ...(decimals === undefined
      ? { maximumFractionDigits: 3 }
      : { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
  }).format(value);
}

/** Texte de `key` dans `language`, repli sur l'anglais, puis sur la clé elle-même. Les
 * paramètres numériques sont mis au format de la langue. */
export function translate(language: Language, key: string, params: Params = {}): string {
  const text =
    lookup(CATALOGS[language] ?? {}, key) ?? lookup(CATALOGS[FALLBACK_LANGUAGE] ?? {}, key) ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => {
    if (!(name in params)) return match;
    const value = params[name];
    return typeof value === "number" ? formatNumber(language, value) : value;
  });
}

/**
 * Langue de l'interface : `?lang=` dans l'URL, sinon le choix mémorisé, sinon la première
 * langue du navigateur prise en charge, sinon l'anglais.
 */
export function detectLanguage(
  search: string,
  stored: string | null,
  browserLanguages: readonly string[],
): Language {
  const fromUrl = new URLSearchParams(search).get("lang");
  if (isLanguage(fromUrl)) return fromUrl;
  if (isLanguage(stored)) return stored;
  for (const tag of browserLanguages) {
    const base = tag.toLowerCase().split("-")[0];
    if (isLanguage(base)) return base;
  }
  return FALLBACK_LANGUAGE;
}
