import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/manrope";
import "./theme/themes.css";
import "./styles.css";

import App from "./App";
import { I18nProvider } from "./i18n/I18nProvider";

const root = document.getElementById("root");
if (root === null) throw new Error("Élément #root introuvable");

createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
);
