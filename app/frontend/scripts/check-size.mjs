// Budget de taille de l'interface compilée (lot 5.2, point n° 2 de la phase 5), vérifié par la
// CI après `npm run build` : tailles compressées (gzip) du fichier principal et des plus gros
// fichiers chargés à la demande (graphiques, écran « Maison » et son graphe). Le fichier
// principal est celui qu'index.html charge : les écrans chargés à la demande ont leurs propres
// fichiers, repérés par leur nom.
//
//   npm run build && npm run size

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const DIST = new URL("../dist/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const ASSETS = join(DIST, "assets");

// Fichier principal : 109,8 Ko au lot 5.2 avant les graphiques, 10 % de marge ; 100,7 Ko une fois
// les écrans secondaires chargés à la demande (lot 5.5) ; 88,4 Ko quand les textes français et
// anglais le sont aussi (qualité des données), au lieu de 120,9 Ko.
const MAIN_KB = 121;
// Graphiques (Recharts) : au plus 150 Ko de plus pour l'écran du plan.
const CHARTS_KB = 150;
// Écran « Maison » (éditeurs de la configuration) : 10,9 Ko quand il est sorti du fichier
// principal, environ 50 % de marge.
const HOME_KB = 16;
// Graphe de la maison (@xyflow/react) : 52,2 Ko, environ 20 % de marge.
const HOME_GRAPH_KB = 64;
// Police Manrope, caractères latins (lot 6b.1) : chargée à part, en parallèle du fichier
// principal ; les autres alphabets ne sont téléchargés que s'ils servent (unicode-range).
const FONT_KB = 32;

const kb = (file) => gzipSync(readFileSync(join(ASSETS, file))).length / 1024;
const html = readFileSync(join(DIST, "index.html"), "utf8");
// Fichier principal : celui qu'index.html exécute, plus ceux qu'il précharge (modulepreload) :
// Vite peut en sortir du code partagé avec un écran chargé à la demande, toujours lu au démarrage.
const startup = [...html.matchAll(/(?:src|href)="[^"]*assets\/([^"]+\.js)"/g)].map((match) => match[1]);
const files = readdirSync(ASSETS);
const chunk = (name) => files.find((file) => file.startsWith(`${name}-`) && file.endsWith(".js"));

const checks = [
  ["fichier principal", startup, MAIN_KB],
  ["graphiques", chunk("Charts"), CHARTS_KB],
  ["écran « Maison »", chunk("HomeScreen"), HOME_KB],
  ["graphe de la maison", chunk("HomeGraph"), HOME_GRAPH_KB],
  ["police", files.find((file) => file.startsWith("manrope-latin-wght-")), FONT_KB, "raw"],
];
let failed = false;
for (const [label, file, budget, mode] of checks) {
  if (!file || file.length === 0) {
    console.error(`ÉCHEC  ${label} : fichier introuvable dans dist/`);
    failed = true;
    continue;
  }
  // Un fichier woff2 est déjà compressé : sa taille brute est celle qui passe sur le réseau.
  const size = Array.isArray(file)
    ? file.reduce((total, name) => total + kb(name), 0)
    : mode === "raw"
      ? readFileSync(join(ASSETS, file)).length / 1024
      : kb(file);
  const ok = size <= budget;
  failed ||= !ok;
  console.log(`${ok ? "ok    " : "ÉCHEC "} ${label} (${[file].flat().join(" + ")}) : ${size.toFixed(1)} Ko compressés, budget ${budget} Ko`);
}
process.exit(failed ? 1 : 0);
