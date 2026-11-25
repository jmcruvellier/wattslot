// Planning des équipements (lot 5.3) : une ligne par équipement sur 24 heures, repère du dernier
// relevé avec son heure, info-bulle au toucher. Faite main (point n° 2 de la phase 5), positions
// en pourcentage de la journée comme la frise de la v1.
// Le réel est une pilule pleine ; le prévu, un crochet posé au-dessus (repère de plan, comme la
// cible d'un graphique à puces). Un bloc prévu que rien de réel ne recouvre et qui reste à venir
// — ou dont on peut encore changer le départ — porte en plus une pilule en pointillé sous son
// crochet. L'énergie est écrite dans les pilules, centrée sur leur plus grande partie visible,
// s'il leur reste assez de place libre ; pas de légende, le détail est dans l'info-bulle.
// Une ligne de batterie qui en réunit plusieurs (toutes, ou celles d'une phase) est suivie d'une
// ligne fine par batterie, avec son seul mesuré : la prévision n'existe que pour l'ensemble.
// Sur la vue Aujourd'hui, le clic sur un bloc prévu d'un équipement — à venir, en cours ou
// passé — ouvre la feuille des autres départs (OtherStarts) et du bouton « Annuler » : changer
// de créneau, annuler la planification du jour ou y revenir, sans quitter l'écran. Sur Demain et
// les jours suivants (`day`), la feuille propose les autres départs et une heure libre ; pas
// d'annulation, qui ne vaut que pour aujourd'hui.
// Partout ailleurs sur une piste, le clic choisit une heure : sous la frise, le prévu et le réel
// de la ligne à cet endroit, ensemble — les blocs sous le clic, sinon ceux de l'heure d'horloge
// touchée — ou la mention qu'il n'y a rien. L'heure choisie reste marquée sur sa ligne.
// Chaque ligne commence par l'icône de son équipement, dans une pastille à la couleur de ses
// blocs, et porte sous son nom une ligne d'état : où en est son cycle (en cours, lancé à…,
// prévu à…, pas lancé) ou, pour une batterie et les autres, l'énergie mesurée, à défaut prévue.
// Avec les heures de la journée (`hours`, vue Aujourd'hui seule), la frise porte en fond les
// heures creuses, au-dessus d'elle une bande de soleil — plus dense quand la production est
// forte, mesurée si elle l'est, prévue sinon — et la phrase du clic dit le tarif et la
// production de l'heure choisie. Une légende de deux mots l'explique sous l'axe.
// Un équipement qui en suit un autre (le sèche-linge après le lave-linge) vient juste sous lui,
// et chacun de ses cycles est relié au cycle qu'il suit par un trait fin (timelineLinks.ts) :
// plein quand il est lancé ou fini, en pointillé tant qu'il est prévu ou pas lancé. Le trait est
// un décor : la dépendance est dite dans le nom de la ligne pour un lecteur d'écran, et dans la
// légende.

import { Fragment, useCallback, useEffect, useState, type MouseEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { minuteOfDay } from "../i18n/homeTime";
import { duration as gapText, hour, kwh } from "./format";
import { freeSpan } from "./timelineSpan";
import { rowLabel } from "./batteryLabel";
import { cycleNames } from "./cycleNames";
import { modeColor } from "./modeColor";
import { laneOffset, linkShapes, stubPx, turnsBack } from "./timelineLinks";
import { hourSun } from "./dayPoints";
import type { Bar, HourPoint, TimelineRow, Timeline } from "./types";
import Icon from "../ui/Icon";
import type { IconName } from "../ui/iconPaths";
import Button from "../ui/Button";
import Sheet from "../ui/Sheet";
import OtherStarts from "./OtherStarts";
import { cancelTask, restoreTask } from "./cancelled";
import { withdrawLaunched } from "./declared";
import type { StartChoice } from "./startChoices";

const AXIS = [0, 4, 8, 12, 16, 20, 24];
// Place libre minimale, en pixels, pour écrire l'énergie d'un bloc (« 12,5 kWh » et ses marges).
const LABEL_MIN_PX = 50;

/** Largeur affichée de la piste (toutes les pistes ont la même), donnée par l'observateur dès le
 * début puis à chaque redimensionnement ; 0 sans ResizeObserver : aucun libellé dans les blocs. */
function useTrackWidth(): [number, (element: HTMLDivElement | null) => void] {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(element.getBoundingClientRect().width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [width, useCallback((node: HTMLDivElement | null) => setElement(node), [])];
}

function color(row: TimelineRow, bar: Bar): string {
  if (bar.action) return bar.action === "charge" ? "var(--charge)" : "var(--discharge)";
  if (row.kind === "runtime") return modeColor(bar.mode);
  return "var(--cycle)";
}

/** Le cycle prévu a-t-il déjà tourné aujourd'hui (un cycle réel commencé, en cours ou fini) ?
 * Lancé, il ne se déplace plus ni ne s'annule plus : son bloc reste une info-bulle. Avec
 * plusieurs cycles du même équipement dans la journée, un cycle réel ne vaut que pour un
 * cycle prévu : le suivant n'est lancé que par une activité commencée après la fin du
 * précédent. */
function launched(row: TimelineRow, bar: Bar, nowMin: number): boolean {
  if (bar.launched) return true; // dit par le serveur : son créneau annoncé peut être à venir
  const planned = row.planned.filter((other) => !other.carried);
  const before = planned[planned.indexOf(bar) - 1];
  const after = before ? before.end_hour : 0;
  return row.actual.some((done) => done.start_hour * 60 <= nowMin && done.start_hour >= after);
}

// Icône d'une ligne, d'après le type de l'équipement dans la maison ; une prise à défaut.
const ICONS: Record<string, IconName> = {
  WashingMachine: "washer",
  Dryer: "dryer",
  Dishwasher: "dishwasher",
  WaterHeater: "water-heater",
  PoolPump: "pool",
};

function rowIcon(row: TimelineRow): IconName {
  if (row.kind === "battery") return "battery";
  return ICONS[row.type ?? ""] ?? (row.kind === "runtime" ? "pool" : "plug");
}

// Couleur de la pastille : celle des blocs de la ligne.
// Écart de démarrage toléré, comme le bilan du serveur (« à l'heure ») : au-delà, la pastille
// de l'écart est mise en avant.
const SHIFT_MIN = 15;

const TONES = { battery: "var(--battery)", cycle: "var(--cycle)", runtime: "var(--pool-eco)" };

/** Fond de la bande de soleil : une teinte par heure, en proportion de la plus forte
 * (``hourSun`` : mesurée, sauf l'heure en cours, prévue). */
function sunBand(hours: HourPoint[], readingHour: number | null): string {
  const sunOf = (point: HourPoint) => hourSun(point, readingHour);
  const top = Math.max(...hours.map(sunOf), 0);
  if (top <= 0) return "none";
  const stops = hours.map((point) => {
    const tint = `color-mix(in srgb, var(--sun) ${Math.round((sunOf(point) / top) * 100)}%, transparent)`;
    return `${tint} ${(point.hour / 24) * 100}% ${((point.hour + 1) / 24) * 100}%`;
  });
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

/** Une piste : ses blocs prévus et réels, sous une clé et un nom (ligne d'équipement, ou batterie
 * d'un groupe). */
type Lane = { key: string; label: string; row: TimelineRow; planned: Bar[]; actual: Bar[] };

/** Heure de la journée sous le clic, lue sur la piste ; `fallback` au clavier ou sans largeur. */
function hourAt(event: MouseEvent<HTMLElement>, fallback: number): number {
  const box = (event.currentTarget.closest(".tl-track") ?? event.currentTarget).getBoundingClientRect();
  if (event.detail === 0 || box.width === 0) return fallback;
  return Math.min(Math.max(((event.clientX - box.left) / box.width) * 24, 0), 23.99);
}

// Minutes depuis minuit maintenant, pour dire si un cycle réel a commencé.
function nowMinute(): number {
  return minuteOfDay();
}

export default function TimelineCard({
  timeline,
  readingHour,
  choices,
  onChanged,
  day,
  hours,
  declared = [],
}: {
  timeline: Timeline;
  readingHour: number | null;
  choices?: Record<string, StartChoice>;
  onChanged?: () => void;
  day?: string; // jour d'un plan à venir ; aucun : aujourd'hui
  hours?: HourPoint[]; // heures de la journée : fond des heures creuses et bande de soleil
  // Cycles déclarés lancés (« C'est lancé ») que les mesures n'ont pas encore vus : leur départ
  // ne se change plus, il faut d'abord revenir sur la déclaration (« Pas encore lancé »).
  declared?: string[];
}) {
  const { language, t } = useI18n();
  // Heure d'horloge choisie d'un clic sur une piste : marquée sur toutes les lignes, son
  // détail affiché sous la frise.
  const [zone, setZone] = useState<number | null>(null);
  const [trackWidth, measureTrack] = useTrackWidth();
  const lang = language === "fr" ? "fr" : "en";
  // Cycle (son identité) et bloc prévu dont la feuille des autres départs est ouverte.
  const [picked, setPicked] = useState<{ device: string; bar: Bar } | null>(null);
  const pickable = choices !== undefined && onChanged !== undefined;
  // Annulation (bouton « Annuler ») et rétablissement, dans et sous la frise.
  const [cancelling, setCancelling] = useState<"idle" | "running" | "failed">("idle");
  const [restoring, setRestoring] = useState<string | null>(null);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const nowMin = day === undefined ? nowMinute() : -1;

  const describe = (row: TimelineRow, bar: Bar, actual: boolean) => {
    const what = bar.action
      ? t(`plan.timeline.${bar.action}`)
      : bar.mode
        ? t("plan.timeline.mode", { mode: bar.mode })
        : (cycleNames(row, timeline.statuses ?? []).get(bar) ?? row.device);
    const tip = actual ? "plan.timeline.tip_actual" : bar.carried ? "plan.timeline.tip_carried" : "plan.timeline.tip_planned";
    return t(tip, {
      start: hour(Math.round(bar.start_hour * 60) / 60, lang),
      end: hour(Math.round(bar.end_hour * 60) / 60, lang),
      what,
      kwh: kwh(bar.energy_kwh),
    });
  };

  // Ligne d'état sous le nom : le bilan du cycle de l'équipement (celui en cours, sinon le
  // dernier lancé, sinon le premier prévu) ; sans cycle jugé, l'énergie mesurée, à défaut prévue.
  const stateLine = (row: TimelineRow): string | null => {
    const own = (timeline.statuses ?? []).filter((status) => (status.appliance ?? status.device) === row.device);
    const status =
      own.find((one) => one.running) ?? [...own].reverse().find((one) => one.actual_start_min !== null) ?? own[0];
    if (row.kind === "cycle" && status) {
      if (status.running) return t("plan.timeline.state.running");
      if (status.actual_start_min !== null)
        return t("plan.timeline.state.started", { time: hour(status.actual_start_min / 60, lang) });
      if (declared.includes(status.device)) return t("requests.state_declared");
      return status.status === "no_cycle"
        ? t("plan.timeline.state.no_cycle")
        : t("plan.timeline.state.planned", { time: hour(status.planned_start_min / 60, lang) });
    }
    const measured = row.actual.length > 0;
    const items = measured ? row.actual : row.planned;
    if (items.length === 0) return null;
    const sum = (action?: string) =>
      kwh(items.reduce((total, bar) => (action && bar.action !== action ? total : total + bar.energy_kwh), 0), 1);
    return t(measured ? "plan.timeline.state.measured" : "plan.timeline.state.energy", {
      kwh: row.kind === "battery" ? `+${sum("charge")} / −${sum("discharge")}` : sum(),
    });
  };

  // Plages d'heures creuses [début, fin[ : une bande par plage, sans joint entre deux heures.
  const offPeak: [number, number][] = [];
  for (const point of hours ?? []) {
    if (!point.off_peak) continue;
    const last = offPeak[offPeak.length - 1];
    if (last && last[1] === point.hour) last[1] = point.hour + 1;
    else offPeak.push([point.hour, point.hour + 1]);
  }
  const sun = hours ? sunBand(hours, readingHour) : "none";
  const links = linkShapes(timeline);

  // Choisit l'heure d'horloge de `at` ; la même une seconde fois : plus d'heure choisie.
  const pick = (at: number) => {
    if (Number.isNaN(at)) return;
    const chosen = Math.floor(at);
    setZone((current) => (current === chosen ? null : chosen));
  };

  // Détail de l'heure choisie : une ligne par équipement qui y a du prévu ou du réel, toutes
  // lignes de la frise confondues. Le prévu et le réel d'un même cycle, d'un même sens de la
  // batterie ou d'une même vitesse sont réunis.
  type Detail = {
    key: string;
    name: string;
    device: string; // équipement de la ligne de la frise
    what: string | null;
    planned?: Bar;
    actual?: Bar;
    cycle: boolean;
  };
  const details = (at: number): Detail[] => {
    const found = new Map<string, Detail>();
    const lanes: Lane[] = timeline.rows.flatMap((row) => [
      { key: row.device, label: rowLabel(row, t), row, planned: row.planned, actual: row.actual },
      ...(row.batteries ?? []).map((battery) => ({
        key: `${row.device}/${battery.key}`,
        label: battery.name,
        row,
        planned: [],
        actual: battery.actual,
      })),
    ]);
    for (const lane of lanes) {
      const names = cycleNames(lane.row, timeline.statuses ?? []);
      const add = (bar: Bar, actual: boolean) => {
        if (!(bar.start_hour < at + 1 && bar.end_hour > at)) return;
        const what = bar.action ? t(`plan.timeline.${bar.action}`) : bar.mode ? t("plan.timeline.mode", { mode: bar.mode }) : null;
        const name = names.get(bar) ?? lane.label;
        const key = `${lane.key}|${name}|${what ?? ""}`;
        const line = found.get(key) ?? { key, name, device: lane.row.device, what, cycle: lane.row.kind === "cycle" };
        if (actual) line.actual ??= bar;
        else line.planned ??= bar;
        found.set(key, line);
      };
      lane.planned.forEach((bar) => add(bar, false));
      lane.actual.forEach((bar) => add(bar, true));
    }
    return [...found.values()];
  };

  // Horaire d'un bloc, en trois morceaux : dans le tableau, les flèches d'une même colonne
  // s'alignent, le début calé à droite et la fin à gauche (styles.css).
  const span = (bar: Bar) => (
    <span className="tl-span">
      <span>{hour(Math.round(bar.start_hour * 60) / 60, lang)}</span> → <span>{hour(Math.round(bar.end_hour * 60) / 60, lang)}</span>
    </span>
  );

  const detail = (at: number) => {
    const lines = details(at);
    // Tarif de l'heure (si la journée a des heures creuses) et production solaire (si elle en a).
    const point = hours?.find((one) => one.hour === at);
    return (
      <div role="status" className="tl-tip">
        <p className="tl-tip-head">
          <strong>
            {hour(at, lang)} → {hour(at + 1, lang)}
          </strong>{" "}
          {point && offPeak.length > 0 && (
            <span className="tl-chip">{t(point.off_peak ? "plan.timeline.detail.off_peak" : "plan.timeline.detail.peak")}</span>
          )}{" "}
          {point && sun !== "none" && (
            <span className="tl-chip">{t("plan.timeline.detail.sun", { kwh: kwh(hourSun(point, readingHour)) })}</span>
          )}
        </p>
        {lines.length === 0 && <p className="dim">{t("plan.timeline.detail.none")}</p>}
        {lines.length > 0 && (
          // Un tableau à la largeur de son contenu, calé à gauche : les colonnes restent serrées
          // sur une fenêtre large. Le prévu et le réel sont deux blocs, l'horaire accolé à son
          // énergie. Sur un téléphone, chaque équipement passe sur deux lignes (styles.css).
          <div role="table" className="tl-table">
            <div role="row" className="tl-table-head">
              <span role="columnheader">{t("plan.timeline.detail.device")}</span>{" "}
              <span role="columnheader" className="tl-block tl-block-span">
                {t("plan.timeline.detail.planned")}
              </span>{" "}
              <span role="columnheader" className="tl-block tl-block-kwh">
                kWh
              </span>{" "}
              <span role="columnheader" className="tl-block tl-block-span">
                {t("plan.timeline.detail.actual")}
              </span>{" "}
              <span role="columnheader" className="tl-block tl-block-kwh">
                kWh
              </span>{" "}
              <span role="columnheader">{t("plan.timeline.detail.gap")}</span>{" "}
            </div>
            {lines.map((line) => {
              const { planned, actual } = line;
              // Écart de démarrage d'un cycle, réel moins prévu.
              const gap =
                line.cycle && planned && actual && !planned.carried
                  ? Math.round((actual.start_hour - planned.start_hour) * 60)
                  : 0;
              // Écart d'énergie du cycle, d'après le bilan du serveur (nul sous son seuil).
              const status =
                line.cycle && planned && actual
                  ? (timeline.statuses ?? []).find((one) => one.device === (planned.cycle ?? line.device))
                  : undefined;
              const percent = status?.energy_gap_percent ?? null;
              const side = (bar: Bar | undefined, label: string) => (
                <>
                  <span role="cell" className="tl-block tl-block-span" data-label={label}>
                    {bar ? span(bar) : <span className="dim">—</span>}
                  </span>{" "}
                  <span role="cell" className={bar ? "tl-block tl-block-kwh" : "tl-block tl-block-kwh tl-none"}>
                    {bar ? kwh(bar.energy_kwh) : <span className="dim">—</span>}
                  </span>{" "}
                </>
              );
              return (
                <div role="row" key={line.key}>
                  {/* Espaces écrites : les cellules sont des boîtes séparées à l'écran, mais leur
                   * texte doit se lire d'une traite (lecteur d'écran, copie). */}
                  <span role="cell" className="tl-table-name">
                    <strong>{line.name}</strong>{" "}
                    {(line.what || planned?.carried) && (
                      <span className="dim">{line.what ?? t("plan.timeline.detail.carried")}</span>
                    )}
                  </span>{" "}
                  {side(planned, t("plan.timeline.detail.planned"))}
                  {side(actual, t("plan.timeline.detail.actual"))}
                  <span role="cell" className={gap === 0 && percent === null ? "tl-table-gap tl-none" : "tl-table-gap"}>
                    {gap !== 0 && (
                      <span className={Math.abs(gap) > SHIFT_MIN ? "tl-chip tl-chip-shift" : "tl-chip"}>
                        {gap > 0 ? "+" : "−"}
                        {gapText(gap, lang)}
                      </span>
                    )}{" "}
                    {percent !== null && (
                      <span className="tl-chip tl-chip-shift">
                        {percent > 0 ? "+" : "−"}
                        {Math.abs(percent)} %
                      </span>
                    )}
                  </span>{" "}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const bars = (lane: Lane, items: Bar[], actual: boolean) =>
    items.map((bar, index) => {
      const row = lane.row;
      const text = describe(row, bar, actual);
      // Un cycle qui finit le lendemain s'arrête à minuit sur la frise du jour.
      const shownEnd = Math.min(bar.end_hour, 24);
      const [free_start, span_end] = freeSpan(items, index);
      const free_end = Math.min(span_end, 24);
      const wide = ((free_end - free_start) / 24) * trackWidth >= LABEL_MIN_PX;
      const duration = shownEnd - bar.start_hour;
      // Départ d'un appareil pas encore lancé — même si son créneau est passé, personne ne l'a
      // démarré : la feuille s'ouvre au clic, changer de créneau ou annuler la planification.
      // Un équipement lancé ou en cours ne se déplace plus : son bloc reste une info-bulle.
      const choice =
        !actual && !bar.carried && pickable && row.kind === "cycle" && !launched(row, bar, nowMin)
          ? choices[bar.cycle ?? row.device]
          : undefined;
      const opens = choice !== undefined;
      // À venir : rien de réel ne le recouvre, et son créneau n'est pas fini (ou son départ se
      // change encore). Lui seul porte une pilule, donc son énergie ; les autres, un crochet.
      const upcoming =
        !actual &&
        !bar.launched &&
        !row.actual.some((done) => done.start_hour < bar.end_hour && done.end_hour > bar.start_hour) &&
        (opens || readingHour === null || bar.end_hour > readingHour);
      const kind = actual ? "tl-actual" : upcoming ? "tl-planned tl-upcoming" : "tl-planned";
      return (
        <button
          key={`${actual ? "a" : "p"}-${index}`}
          type="button"
          className={opens ? `tl-bar ${kind} tl-pickable` : `tl-bar ${kind}`}
          style={{
            left: `${(bar.start_hour / 24) * 100}%`,
            width: `max(3px, ${(duration / 24) * 100}%)`,
            ["--bar" as string]: color(row, bar),
          }}
          title={text}
          aria-label={text}
          onClick={(event) => {
            event.stopPropagation();
            if (opens) setPicked({ device: bar.cycle ?? row.device, bar });
            else pick(hourAt(event, (bar.start_hour + shownEnd) / 2));
          }}
        >
          {wide && (actual || upcoming) && (
            <span
              className="tl-value"
              aria-hidden="true"
              style={{ left: `${(((free_start + free_end) / 2 - bar.start_hour) / duration) * 100}%` }}
            >
              {kwh(bar.energy_kwh, 1)} kWh
            </span>
          )}
        </button>
      );
    });

  const track = (lane: Lane, measured: boolean, single: boolean) => (
    // Les blocs sont des boutons, pour le clavier ; le reste de la piste répond à la souris et
    // au doigt.
    <div
      className={single ? "tl-track tl-track-single" : "tl-track"}
      ref={measured ? measureTrack : undefined}
      onClick={(event) => pick(hourAt(event, Number.NaN))}
    >
      {offPeak.map(([start, end]) => (
        <span
          key={start}
          className="tl-offpeak"
          style={{ left: `${(start / 24) * 100}%`, width: `${((end - start) / 24) * 100}%` }}
        />
      ))}
      {zone !== null && <span className="tl-zone" style={{ left: `${(zone / 24) * 100}%` }} />}
      {bars(lane, lane.planned, false)}
      {bars(lane, lane.actual, true)}
      {!single &&
        (links.get(lane.key) ?? []).map((shape, index) => {
          // Un morceau par virage (styles.css). Tracé ordinaire, deux morceaux : le long de la
          // ligne du bloc suivi puis la descente, la fin de la descente puis le long de cette
          // ligne. Tracé de repli, quatre : la sortie du bloc suivi, la descente et le couloir,
          // la fin du couloir et la descente, l'entrée dans le bloc qui suit.
          const direct = shape.via !== null;
          const back = !direct && turnsBack(shape, trackWidth) ? " tl-link-back" : "";
          const kind = `tl-link${shape.started ? "" : " tl-link-dashed"}${back}`;
          const style = {
            ["--x1" as string]: `${(shape.from / 24) * 100}%`,
            ["--x2" as string]: `${(shape.to / 24) * 100}%`,
            ["--via" as string]: `${((shape.via ?? shape.to) / 24) * 100}%`,
            ["--half" as string]: `${((shape.to - shape.from) / 48) * 100}%`,
            ["--stub" as string]: `${stubPx(shape, trackWidth)}px`,
            ["--lane" as string]: `${laneOffset(shape)}rem`,
            ["--skip" as string]: shape.skip,
          };
          return (
            <Fragment key={`l-${index}`}>
              {(direct ? ["across", "into"] : ["out", "down", "along", "in"]).map((part) => (
                <span key={part} aria-hidden="true" className={`${kind} tl-link-${part}`} style={style} />
              ))}
            </Fragment>
          );
        })}
      {readingHour !== null && <span className="tl-now" style={{ left: `${(readingHour / 24) * 100}%` }} />}
    </div>
  );

  const run = async (change: () => Promise<unknown>) => {
    setCancelling("running");
    try {
      await change();
      setCancelling("idle");
      setPicked(null); // le plan recalcule, la frise va suivre
      onChanged?.();
    } catch {
      setCancelling("failed");
    }
  };

  const restore = async (device: string) => {
    setRestoring(device);
    setRestoreFailed(false);
    try {
      await restoreTask(device);
      setRestoring(null);
      onChanged?.();
    } catch {
      setRestoring(null);
      setRestoreFailed(true);
    }
  };

  return (
    <article className="card card-wide" aria-label={t("plan.timeline.title")}>
      <h3>
        <Icon name="planning" size={20} /> {t("plan.timeline.title")}
      </h3>
      {timeline.empty ? (
        <p className="dim">
          {timeline.empty === "no_surplus"
            ? t("plan.timeline.no_surplus", {
                production: kwh(timeline.production_kwh, 1),
                consumption: kwh(timeline.consumption_kwh, 1),
              })
            : t("plan.timeline.nothing")}
        </p>
      ) : (
        <div className="tl">
          {readingHour !== null && (
            <div className="tl-row" aria-hidden="true">
              <span />
              <div className="tl-now-row">
                <span className="tl-now-label" style={{ ["--now" as string]: `${(readingHour / 24) * 100}%` }}>
                  {hour(Math.round(readingHour * 60) / 60, lang)}
                </span>
              </div>
            </div>
          )}
          {sun !== "none" && (
            <div className="tl-row" aria-hidden="true">
              <span />
              <div className="tl-sun" style={{ background: sun }} />
            </div>
          )}
          {timeline.rows.map((row, index) => (
            <Fragment key={row.device}>
              <div className="tl-row" aria-label={rowLabel(row, t)}>
                <span className="tl-label tl-device">
                  <span className="tl-icon" style={{ ["--bar" as string]: TONES[row.kind] }}>
                    <Icon name={rowIcon(row)} size={18} />
                  </span>
                  <span className="tl-name">
                    <span>{rowLabel(row, t)}</span>
                    {row.follows && (
                      <span className="visually-hidden">{t("plan.timeline.follows", { device: row.follows })}</span>
                    )}
                    {stateLine(row) && <small>{stateLine(row)}</small>}
                  </span>
                </span>
                {track(
                  { key: row.device, label: rowLabel(row, t), row, planned: row.planned, actual: row.actual },
                  index === 0,
                  false,
                )}
              </div>
              {/* Ligne qui réunit plusieurs batteries : le mesuré de chacune dessous, sur un seul
               * couloir. La prévision n'existe que pour l'ensemble. */}
              {(row.batteries ?? []).map((battery) => (
                <div
                  key={battery.key}
                  className="tl-row"
                  aria-label={t("plan.timeline.battery_measured", { name: battery.name })}
                >
                  <span className="tl-label tl-sub-label" title={t("plan.timeline.battery_measured", { name: battery.name })}>
                    {battery.name}
                  </span>
                  {track(
                    { key: `${row.device}/${battery.key}`, label: battery.name, row, planned: [], actual: battery.actual },
                    false,
                    true,
                  )}
                </div>
              ))}
            </Fragment>
          ))}
          <div className="tl-row" aria-hidden="true">
            <span />
            <div className="tl-axis">
              {AXIS.map((h) => (
                <span key={h} style={{ left: `${(h / 24) * 100}%` }}>
                  {hour(h, lang)}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
      {!timeline.empty && (sun !== "none" || offPeak.length > 0 || links.size > 0) && (
        <p className="tl-legend dim">
          {sun !== "none" && <span className="tl-legend-sun">{t("plan.timeline.legend_sun")}</span>}
          {offPeak.length > 0 && <span className="tl-legend-offpeak">{t("plan.timeline.legend_off_peak")}</span>}
          {links.size > 0 && <span className="tl-legend-link">{t("plan.timeline.legend_link")}</span>}
        </p>
      )}
      {/* Planifications annulées pour aujourd'hui, rétablies d'un clic ; ailleurs que sur la vue
       * Aujourd'hui, la liste est vide et rien ne s'affiche. */}
      {pickable && (timeline.cancelled ?? []).length > 0 && (
        <p className="tl-cancelled">
          <span className="dim">{t("plan.timeline.cancelled")}</span>{" "}
          {(timeline.cancelled ?? []).map((device) => (
            <Button
              key={device}
              icon="refresh"
              disabled={restoring !== null}
              aria-label={t("plan.timeline.restore", { device })}
              onClick={() => void restore(device)}
            >
              {t("plan.timeline.restore", { device })}
            </Button>
          ))}
          {restoreFailed && <span role="alert">{t("plan.timeline.restore_failed")}</span>}
        </p>
      )}
      {zone !== null && !timeline.empty && detail(zone)}
      {picked && (
        <Sheet
          open
          title={t("plan.timeline.choice_title", { device: picked.device })}
          onClose={() => setPicked(null)}
        >
          {/* Comme la ligne du créneau de « Prochaine action » : le texte atténué (dim) devient
           * illisible sur certains thèmes. */}
          <p>
            {t("plan.timeline.choice_slot", {
              start: hour(Math.round(picked.bar.start_hour * 60) / 60, lang),
              end: hour(Math.round(picked.bar.end_hour * 60) / 60, lang),
              kwh: kwh(picked.bar.energy_kwh),
            })}
          </p>
          {declared.includes(picked.device) ? (
            // Déclaré lancé : ni autre départ ni annulation tant qu'on n'est pas revenu dessus.
            <p className="other-starts-buttons">
              {t("today.next.declared", { device: picked.device })}{" "}
              <Button
                icon="refresh"
                disabled={cancelling === "running"}
                onClick={() => void run(() => withdrawLaunched(picked.device))}
              >
                {t("today.next.undo")}
              </Button>
            </p>
          ) : (
            <OtherStarts
              device={picked.device}
              alternatives={choices?.[picked.device]?.alternatives ?? []}
              chosen={choices?.[picked.device]?.chosen ?? false}
              onChanged={() => {
                setPicked(null); // le plan recalcule, la frise va suivre
                onChanged?.();
              }}
              day={day}
              freeFrom={nowMin}
            />
          )}
          {day === undefined && !declared.includes(picked.device) && (
            <p className="other-starts-buttons">
              <Button
                icon="close"
                disabled={cancelling === "running"}
                onClick={() => void run(() => cancelTask(picked.device))}
              >
                {t("plan.timeline.cancel")}
              </Button>
            </p>
          )}
          {day === undefined && cancelling === "failed" && (
            <p role="alert">{t("plan.timeline.cancel_failed")}</p>
          )}
        </Sheet>
      )}
    </article>
  );
}
