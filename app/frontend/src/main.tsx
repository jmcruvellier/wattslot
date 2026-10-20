import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/manrope";
import "./theme/themes.css";
import "./styles.css";

import App from "./App";
import { CurrencyProvider } from "./i18n/currency";
import { I18nProvider } from "./i18n/I18nProvider";
import { detectLanguage, FALLBACK_LANGUAGE, loadCatalog, readStoredLanguage } from "./i18n/translate";

const root = document.getElementById("root");
if (root === null) throw new Error("Élément #root introuvable");

// Textes de la langue de l'interface lus avant le premier affichage ; l'anglais, langue de
// secours, à côté. Un échec n'empêche pas d'afficher (l'anglais, sinon les clés).
const language = detectLanguage(window.location.search, readStoredLanguage(), navigator.languages ?? []);
void loadCatalog(FALLBACK_LANGUAGE).catch(() => undefined);
await loadCatalog(language).catch(() => loadCatalog(FALLBACK_LANGUAGE).catch(() => undefined));

createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <CurrencyProvider>
        <App />
      </CurrencyProvider>
    </I18nProvider>
  </StrictMode>,
);
