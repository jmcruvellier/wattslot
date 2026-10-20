import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { loadCatalog } from "../i18n/translate";

// Catalogues chargés à la demande dans l'application : le français et l'anglais, langues des
// tests, prêts avant le premier rendu.
await Promise.all([loadCatalog("fr"), loadCatalog("en")]);

// Sans les globales de Vitest, Testing Library ne démonte pas les rendus entre deux tests.
afterEach(() => {
  cleanup();
});
