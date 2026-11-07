// Heure de la maison : fuseau de Home Assistant (api/health), lu avant le premier affichage
// (main.tsx). Les heures du plan sont dans ce fuseau ; le navigateur peut être ailleurs
// (application compagnon en voyage). Sans fuseau connu (HA pas encore connecté), celui du
// navigateur, comme avant.

let zone: string | undefined;

function valid(value: string): boolean {
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

export function setHomeTimeZone(value: string | null | undefined): void {
  zone = value && valid(value) ? value : undefined;
}

export function homeTimeZone(): string | undefined {
  return zone;
}

/** Options d'Intl avec le fuseau de la maison, pour afficher un instant. */
export function zoned<T extends Intl.DateTimeFormatOptions>(options?: T): T & { timeZone?: string } {
  return { ...(options ?? ({} as T)), ...(zone ? { timeZone: zone } : {}) };
}

/** Date et heure murale de ``moment`` dans le fuseau de la maison. */
function wall(moment: Date): { year: number; month: number; day: number; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    ...zoned(),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(moment);
  const part = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { year: part("year"), month: part("month"), day: part("day"), hour: part("hour"), minute: part("minute") };
}

/** Minutes depuis minuit, à l'heure de la maison (``moment`` : maintenant par défaut). */
export function minuteOfDay(moment: Date = new Date()): number {
  const { hour, minute } = wall(moment);
  return hour * 60 + minute;
}

/** Heure fractionnaire (14,5 pour 14 h 30), à l'heure de la maison. */
export function hourOfDay(moment: Date): number {
  return minuteOfDay(moment) / 60;
}

/** Jour « AAAA-MM-JJ » de ``moment`` à l'heure de la maison. */
export function homeDay(moment: Date = new Date()): string {
  const { year, month, day } = wall(moment);
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Minuit du jour ``day`` (« AAAA-MM-JJ ») à l'heure de la maison, en instant. Les jours de
 * changement d'heure durent 23 ou 25 h : la fin d'un jour est le minuit du suivant. */
export function homeMidnight(day: string): Date {
  const [year, month, date] = day.split("-").map(Number);
  const target = Date.UTC(year, month - 1, date);
  // Écart du fuseau à cet instant, corrigé une fois (minuit juste après un changement d'heure).
  let moment = target;
  for (let i = 0; i < 2; i += 1) {
    const w = wall(new Date(moment));
    const shown = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute);
    moment -= shown - target;
  }
  return new Date(moment);
}

/** Jour suivant de « AAAA-MM-JJ ». */
export function nextDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, date + 1)).toISOString().slice(0, 10);
}

/** Lit le fuseau de la maison ; sans réponse rapide, garde celui du navigateur. */
export async function loadHomeTimeZone(timeoutMs = 3000): Promise<void> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch("api/health", { signal: controller.signal });
    if (response.ok) {
      const health = (await response.json()) as { time_zone?: string | null };
      setHomeTimeZone(health.time_zone);
    }
  } catch {
    // serveur injoignable : fuseau du navigateur
  } finally {
    window.clearTimeout(timer);
  }
}
