import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { setNumberLanguage } from "../plan/format";
import {
  detectLanguage,
  isLoaded,
  loadCatalog,
  readStoredLanguage,
  STORAGE_KEY,
  translate,
  type Language,
  type Params,
} from "./translate";

function storeLanguage(language: Language): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // Stockage indisponible (navigation privée) : le choix vaut pour la session seulement.
  }
}

interface I18nValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: string, params?: Params) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() =>
    detectLanguage(window.location.search, readStoredLanguage(), navigator.languages ?? []),
  );

  // Catalogue chargé à la demande (celui du démarrage l'est avant le premier affichage) :
  // l'anglais s'affiche le temps de le lire.
  const [loaded, setLoaded] = useState(0);
  useEffect(() => {
    document.documentElement.lang = language;
    if (isLoaded(language)) return;
    let active = true;
    loadCatalog(language)
      .then(() => {
        if (active) setLoaded((count) => count + 1);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [language]);
  setNumberLanguage(language);

  const setLanguage = useCallback((next: Language) => {
    storeLanguage(next);
    setLanguageState(next);
  }, []);

  const value = useMemo<I18nValue>(
    () => ({
      language,
      setLanguage,
      t: (key, params) => translate(language, key, params),
    }),
    // `loaded` : recalculé quand un catalogue chargé à la demande arrive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [language, setLanguage, loaded],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (value === null) throw new Error("useI18n doit être utilisé dans un I18nProvider");
  return value;
}
