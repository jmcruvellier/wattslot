// Graphiques chargés à la demande (Recharts, point n° 2 de la phase 5) : un seul chargement du
// module, partagé par toutes les cartes des vues de jour et de la semaine.

import { lazy } from "react";

let charts: Promise<typeof import("./Charts")> | null = null;
const loadCharts = () => (charts ??= import("./Charts"));

export const EnergyChart = lazy(() => loadCharts().then((m) => ({ default: m.EnergyChart })));
export const SocChart = lazy(() => loadCharts().then((m) => ({ default: m.SocChart })));
export const GridChart = lazy(() => loadCharts().then((m) => ({ default: m.GridChart })));
export const WeekChart = lazy(() => loadCharts().then((m) => ({ default: m.WeekChart })));
