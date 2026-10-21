// Ce que la maison possède (/api/home/features) : sans panneaux, rien sur le soleil ; sans
// batterie, rien sur la batterie (essai d'installation du 21/10/2026). Tant que la réponse
// manque, tout est supposé présent : rien ne disparaît par erreur.

import { useEffect, useState } from "react";

import { getJson } from "../api";

export interface HomeFeatures {
  solar: boolean;
  battery: boolean;
  appliances: number; // équipements placés par le calcul
}

export const ALL_FEATURES: HomeFeatures = { solar: true, battery: true, appliances: 1 };

export function useHomeFeatures(): HomeFeatures {
  const [features, setFeatures] = useState<HomeFeatures>(ALL_FEATURES);
  useEffect(() => {
    const controller = new AbortController();
    getJson<HomeFeatures>("api/home/features", controller.signal)
      .then(setFeatures)
      .catch(() => undefined); // sans réponse : tout reste affiché
    return () => controller.abort();
  }, []);
  return features;
}
