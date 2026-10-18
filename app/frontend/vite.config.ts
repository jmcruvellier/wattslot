import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Chemins relatifs : l'interface est servie derrière l'ingress de Home Assistant
  // (préfixe d'URL variable) comme en mode autonome.
  base: "./",
  server: {
    proxy: {
      "/api": "http://localhost:8100",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Les thèmes sont lus tels quels par leur test (contrastes, mêmes variables partout).
    // styles.css, seulement en texte brut : son test vérifie l'alignement des blocs.
    css: { include: [/themes\.css/, /styles\.css\?raw$/] },
  },
});
