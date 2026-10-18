// Nouvelle version de l'application (lot 7.1, point d'interface n° 4) : le navigateur lit la
// dernière release du dépôt public sur l'API de GitHub, au chargement puis toutes les heures tant
// qu'un onglet est ouvert. Le résultat est gardé dans le navigateur et partagé entre les onglets :
// GitHub n'est interrogé qu'une fois par heure. Le serveur ne fait aucun appel sortant de plus.

import { createContext, useContext, useEffect, useState } from "react";

// Dépôt public (phase 7) : seul endroit où il est nommé.
export const RELEASES_URL = "https://api.github.com/repos/jmcruvellier/wattslot/releases/latest";
export const UPDATE_CHECK_MS = 60 * 60 * 1000;
// Relecture du résultat gardé (par exemple celui d'un autre onglet) ; GitHub n'est appelé que si
// la dernière vérification a plus d'une heure.
export const UPDATE_TICK_MS = 5 * 60 * 1000;
export const UPDATE_STORAGE_KEY = "updates.latest";

export interface LatestRelease {
  version: string;
  url: string;
}

interface Checked {
  checked_at: number;
  release: LatestRelease | null; // null : vérification impossible (hors ligne, dépôt absent…)
}

export type UpdateState =
  | { status: "unknown" }
  | { status: "unavailable" }
  | { status: "current"; latest: LatestRelease }
  | { status: "available"; latest: LatestRelease };

const SEMVER = /^(\d+)\.(\d+)\.(\d+)$/;

/** Vrai si ``candidate`` (X.Y.Z) est plus récente que ``current`` ; faux si l'une n'est pas X.Y.Z. */
export function isNewer(candidate: string, current: string): boolean {
  const a = SEMVER.exec(candidate);
  const b = SEMVER.exec(current);
  if (!a || !b) return false;
  for (let i = 1; i <= 3; i += 1) {
    if (Number(a[i]) !== Number(b[i])) return Number(a[i]) > Number(b[i]);
  }
  return false;
}

function readChecked(): Checked | null {
  try {
    const raw = window.localStorage.getItem(UPDATE_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Checked) : null;
  } catch {
    return null;
  }
}

function writeChecked(checked: Checked) {
  try {
    window.localStorage.setItem(UPDATE_STORAGE_KEY, JSON.stringify(checked));
  } catch {
    // Stockage refusé (navigation privée…) : la vérification reprendra au prochain passage.
  }
}

async function fetchLatest(): Promise<LatestRelease | null> {
  try {
    const response = await fetch(RELEASES_URL, { headers: { Accept: "application/vnd.github+json" } });
    if (!response.ok) return null;
    const release = (await response.json()) as { tag_name?: unknown; html_url?: unknown };
    const version = typeof release.tag_name === "string" ? release.tag_name.replace(/^v/, "") : "";
    if (!SEMVER.test(version) || typeof release.html_url !== "string") return null;
    return { version, url: release.html_url };
  } catch {
    return null;
  }
}

// Une seule requête à la fois pour tout l'onglet.
let pending: Promise<Checked> | null = null;

function checkNow(): Promise<Checked> {
  pending ??= fetchLatest()
    .then((release) => {
      const checked = { checked_at: Date.now(), release };
      writeChecked(checked);
      return checked;
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

function isFresh(checked: Checked | null): checked is Checked {
  return checked !== null && Date.now() - checked.checked_at < UPDATE_CHECK_MS;
}

/** État de la dernière version par rapport à ``current`` (version servie par l'application). */
export function useUpdate(current: string | null): UpdateState {
  const [checked, setChecked] = useState<Checked | null>(readChecked);
  useEffect(() => {
    let active = true;
    const tick = () => {
      const saved = readChecked();
      const done = isFresh(saved) ? Promise.resolve(saved) : checkNow();
      void done.then((found) => {
        if (active) setChecked(found);
      });
    };
    tick();
    const timer = window.setInterval(tick, UPDATE_TICK_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  if (!checked || !current) return { status: "unknown" };
  if (!checked.release) return { status: "unavailable" };
  return isNewer(checked.release.version, current)
    ? { status: "available", latest: checked.release }
    : { status: "current", latest: checked.release };
}

export const UpdateContext = createContext<UpdateState>({ status: "unknown" });

export function useUpdateState(): UpdateState {
  return useContext(UpdateContext);
}
