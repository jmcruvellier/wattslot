// Écran Aujourd'hui (lot 6b.3) : répond à « que dois-je faire, et quand ? » et « que se
// passe-t-il maintenant ? ». En panneaux à petit titre (ui/Panel) : la prochaine action (son
// heure de fin, sa raison en quelques mots, ses boutons) et le moment (quatre tuiles, le dernier
// quart d'heure) côte à côte ; la frise du jour ; puis les indicateurs du plan à côté de la
// batterie et du soleil, en lignes « libellé, valeur ». Sur téléphone, les panneaux s'empilent
// dans cet ordre. Le détail (agenda, raisons, courbes) est dans Planning et Courbes. Vue relue
// toutes les minutes.

import { useEffect, useState } from "react";

import { ApiError, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { hourOfDay, minuteOfDay, zoned } from "../i18n/homeTime";
import { clock, kwh, percent } from "../plan/format";
import { RUN_EVENT } from "../plan/planView";
import { IndicatorsCard } from "../plan/InsightCards";
import { TrendMark } from "../plan/SummaryCards";
import { DEFAULT_LAYOUT } from "../plan/layout";
import TimelineCard from "../plan/TimelineCard";
import { startChoices } from "../plan/startChoices";
import { unplacedNotices } from "../plan/unplaced";
import { cancelTask } from "../plan/cancelled";
import { declareLaunched, withdrawLaunched } from "../plan/declared";
import OtherStarts from "../plan/OtherStarts";
import { BatteryList } from "../plan/BatteryList";
import DiscardedNote from "../plan/DiscardedNote";
import ProvisionalNote from "../plan/ProvisionalNote";
import { shortReason } from "../plan/shortReason";
import { useHomeFeatures } from "../home/features";
import type { DayView, LineKey, Now } from "../plan/types";
import Button from "../ui/Button";
import Icon from "../ui/Icon";
import Panel from "../ui/Panel";
import StateMessage from "../ui/StateMessage";

export const REFRESH_MS = 60_000;

type Load =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error" }
  // ``stale`` : le dernier rafraîchissement a échoué, la vue affichée est la précédente.
  | { status: "ready"; view: DayView; stale?: boolean };

function readingHour(view: DayView): number | null {
  if (!view.actual_updated_at) return null;
  return hourOfDay(new Date(view.actual_updated_at));
}

/** Watts → « 48 W » sous 1 kW (« 0,0 kW » ferait croire à une puissance nulle), « 1,8 kW » au-delà. */
function kw(watts: number): string {
  const value = Math.round(Math.abs(watts));
  return value < 1000 ? `${kwh(value, 0)} W` : `${kwh(value / 1000, 1)} kW`;
}

/** Tendance d'une ligne au relevé (mesuré contre estimé), en pilule en tête de carte ; rien sans
 * mesure. Pilule et non marque des cartes de résumé : elle doit se lire d'un coup d'œil. */
function TrendBadge({ view, line }: { view: DayView; line: LineKey }) {
  const { t } = useI18n();
  const trend = view.cards?.at_reading.find((card) => card.key === line)?.trend;
  if (!trend || trend.direction === "none") return null;
  return <TrendMark trend={trend} label={t("today.trend")} className="trend-pill" />;
}

export default function TodayView({ onNavigate }: { onNavigate?: (target: string) => void }) {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0); // « Réessayer »

  useEffect(() => {
    const controller = new AbortController();
    const read = () =>
      getJson<DayView>(`api/views/today?lang=${language}`, controller.signal)
        .then((view) => setLoad({ status: "ready", view }))
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          if (error instanceof ApiError && error.status === 404) {
            setLoad({ status: "missing" });
            return;
          }
          // Réseau pas encore revenu (téléphone qui se réveille…) : la vue reste, avec un mot ;
          // l'écran d'erreur seulement si rien n'a encore pu être lu.
          setLoad((current) => (current.status === "ready" ? { ...current, stale: true } : { status: "error" }));
        });
    void read();
    const timer = window.setInterval(() => void read(), REFRESH_MS);
    // « Calculer » ou « Rafraîchir » réussi dans la barre de titre : relecture immédiate.
    const onRun = () => void read();
    window.addEventListener(RUN_EVENT, onRun);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener(RUN_EVENT, onRun);
    };
  }, [language, attempt]);

  const retry = () => {
    setLoad({ status: "loading" });
    setAttempt((count) => count + 1);
  };
  if (load.status === "loading") return <StateMessage kind="loading" title={t("today.loading")} />;
  if (load.status === "missing") return <StateMessage kind="empty" title={t("today.no_plan")} />;
  if (load.status === "error") return <StateMessage kind="error" title={t("today.error")} onRetry={retry} />;
  const { view } = load;
  const produced = view.hours.reduce((total, h) => total + (h.production_actual_kwh ?? 0), 0);
  const measuredHours = view.hours.some((h) => h.production_actual_kwh !== null);
  // Total attendu : le mesuré puis le prévu, comme le bandeau météo de Planning. La somme des
  // prévisions seules pouvait être inférieure à ce qui est déjà produit (« 1,2 kWh prévus »
  // à côté de « 1,5 kWh déjà produits »).
  const expected = view.weather?.production_kwh ?? view.summary.production_kwh;

  const unplaced = unplacedNotices(view.notices);
  const hasBattery = view.battery_capacity_kwh !== null;
  const hasSun = view.solar !== false;
  const hasNow = view.now != null && view.now.sentence !== null;

  return (
    <div className="today">
      {load.stale && (
        <p className="card discarded-note" role="status">
          {t("today.stale")}
        </p>
      )}
      {/* Mesures impossibles du jour seulement : celles d'hier ne sont plus d'actualité ici. */}
      <DiscardedNote hours={view.discarded_hours ?? []} />
      <ProvisionalNote view={view} />
      {/* Côte à côte quand la largeur le permet ; sans mesures du moment, la prochaine action
          prend toute la largeur. */}
      <div className={hasNow ? "today-row today-row-split" : "today-row"}>
        <NextActionCard view={view} onChanged={() => setAttempt((count) => count + 1)} onNavigate={onNavigate} />
        <NowCard now={view.now ?? null} />
      </div>
      {/* Appareils demandés que le calcul n'a pas placés : sans bloc ni prochaine action. */}
      {unplaced.length > 0 && (
        <ul className="notices" aria-label={t("today.unplaced")}>
          {unplaced.map((notice, index) => (
            <li key={`${notice.code}-${index}`} className="pill pill-warning">
              <Icon name="warning" size={18} /> {notice.text}
            </li>
          ))}
        </ul>
      )}
      {/* La frise reprend les autres départs des blocs pas encore lancés (feuille au clic). */}
      <TimelineCard
        timeline={view.timeline}
        readingHour={readingHour(view)}
        choices={startChoices(view)}
        onChanged={() => setAttempt((count) => count + 1)}
        hours={view.hours}
      />
      <div className={hasBattery || hasSun ? "today-row today-row-split" : "today-row"}>
        <IndicatorsCard view={view} layout={DEFAULT_LAYOUT.indicators} compact />
        {(hasBattery || hasSun) && (
          <div className="today-stack">
            {hasBattery && (
              <Panel icon="battery" title={t("today.battery.eyebrow")} meta={<TrendBadge view={view} line="soc" />}>
                <dl className="indicators">
                  <div className="indicator">
                    <dt>{t("today.battery.now_label")}</dt>
                    <dd>{t("today.battery.end_value", { pct: percent(view.now?.soc_percent ?? null) })}</dd>
                  </div>
                  <div className="indicator">
                    <dt>{t("today.battery.end_label")}</dt>
                    <dd>{t("today.battery.end_value", { pct: percent(view.summary.soc_end_percent) })}</dd>
                  </div>
                </dl>
                {/* Plusieurs batteries : l'état de charge de chacune, sous celui de la maison. */}
                {(view.now?.batteries?.length ?? 0) > 1 && <BatteryList batteries={view.now?.batteries ?? []} />}
              </Panel>
            )}
            {hasSun && (
              <Panel icon="today" title={t("today.sun.eyebrow")} meta={<TrendBadge view={view} line="production" />}>
                <dl className="indicators">
                  <div className="indicator">
                    <dt>{t("today.sun.forecast_label")}</dt>
                    <dd>{kwh(expected, 1)} kWh</dd>
                  </div>
                  <div className="indicator">
                    <dt>{t("today.sun.done_label")}</dt>
                    <dd>{measuredHours ? `${kwh(produced, 1)} kWh` : "—"}</dd>
                  </div>
                </dl>
              </Panel>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Le moment en quatre tuiles (moyenne du dernier quart d'heure ; la plage est en infobulle, la
 * phrase du serveur pour les lecteurs d'écran). Sans mesures du moment, pas de panneau. */
function NowCard({ now }: { now: Now | null }) {
  const { language, t } = useI18n();
  if (now === null || now.sentence === null) return null;
  const tiles: { key: string; label: string; value: string }[] = [];
  if (now.production_w !== null) tiles.push({ key: "sun", label: t("today.now.panels"), value: kw(now.production_w) });
  if (now.consumption_w !== null) tiles.push({ key: "home", label: t("today.now.home"), value: kw(now.consumption_w) });
  if (now.battery_w !== null || now.soc_percent !== null) {
    const parts = [now.soc_percent !== null ? `${percent(now.soc_percent)} %` : null];
    if (now.battery_w) parts.push(t(now.battery_w > 0 ? "today.now.charging" : "today.now.discharging", { kw: kw(now.battery_w) }));
    tiles.push({ key: "battery", label: t("today.now.battery"), value: parts.filter(Boolean).join(" · ") });
  }
  if (now.grid_w !== null) {
    // Le libellé dit le sens (« Achat », « Surplus »), la valeur la puissance.
    const label = now.grid_w > 0 ? "today.now.grid_buying" : now.grid_w < 0 ? "today.now.grid_selling" : "today.now.grid";
    tiles.push({ key: "grid", label: t(label), value: now.grid_w === 0 ? t("today.now.idle") : kw(now.grid_w) });
  }
  const measured =
    now.since && now.until
      ? t("today.now.measured", {
          start: new Date(now.since).toLocaleTimeString(language, zoned({ hour: "2-digit", minute: "2-digit" })),
          end: new Date(now.until).toLocaleTimeString(language, zoned({ hour: "2-digit", minute: "2-digit" })),
        })
      : undefined;
  return (
    <Panel icon="plug" title={t("today.now.eyebrow")}>
      <p className="visually-hidden">{now.sentence}</p>
      {tiles.length > 0 && (
        <dl className="now-tiles" title={measured}>
          {tiles.map((tile) => (
            <div key={tile.key} className="now-tile">
              <dt>{tile.label}</dt>
              <dd>{tile.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </Panel>
  );
}

/** Appareils marqués « C'est lancé » dont le cycle n'est pas encore reconnu dans les mesures :
 * un clic par erreur se reprend, l'appareil redevient la prochaine action. */
function DeclaredLaunches({ devices, onChanged }: { devices: string[]; onChanged: () => void }) {
  const { t } = useI18n();
  const [undoing, setUndoing] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  if (devices.length === 0) return null;

  const undo = async (device: string) => {
    setFailed(false);
    setUndoing(device);
    try {
      await withdrawLaunched(device);
      onChanged();
    } catch {
      setFailed(true);
    } finally {
      setUndoing(null);
    }
  };

  return (
    <div className="declared-launches">
      {devices.map((device) => (
        <p key={device} className="other-starts-buttons">
          {t("today.next.declared", { device })}{" "}
          <Button icon="refresh" disabled={undoing !== null} onClick={() => void undo(device)}>
            {t("today.next.undo")}
          </Button>
        </p>
      ))}
      {failed && <p role="alert">{t("today.next.undo_failed")}</p>}
    </div>
  );
}

function NextActionCard({
  view,
  onChanged,
  onNavigate,
}: {
  view: DayView;
  onChanged: () => void;
  onNavigate?: (target: string) => void;
}) {
  const { language, t } = useI18n();
  const features = useHomeFeatures();
  const action = view.next_action ?? null;
  const declared = <DeclaredLaunches devices={view.declared_launches ?? []} onChanged={onChanged} />;
  const [launching, setLaunching] = useState(false);
  const [launchFailed, setLaunchFailed] = useState(false);
  // Appareil dont le rappel vient d'être posé ici : le bloc peut passer à un autre appareil
  // sans rechargement, et son rappel à lui n'est pas posé.
  const [reminded, setReminded] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelFailed, setCancelFailed] = useState(false);
  // Autres départs (ceux du plan et l'heure libre) : dépliés à la demande.
  const [otherTime, setOtherTime] = useState(false);

  if (action === null) {
    // Aucun appareil placé par le calcul (tableau Énergie sans appareil) : rien ne sera jamais à
    // lancer tant qu'on n'en ajoute pas un.
    const noAppliance = features.appliances === 0;
    // Pourquoi rien n'est à lancer, d'après le serveur : tout est lancé, planification
    // annulée, ou aucun appareil prévu aujourd'hui ; sinon l'heure prévue est passée.
    const reason = noAppliance ? "no_appliance" : (view.idle_reason ?? "none");
    const devices = (view.timeline.cancelled ?? []).join(", ");
    return (
      <Panel icon="play" title={t("today.next.eyebrow")} className="next-action">
        <h3 className="next-action-title">{t(`today.next.${reason}`)}</h3>
        <p className="next-action-line">{t(`today.next.${reason}_help`, { devices })}</p>
        {noAppliance && onNavigate && (
          <Button variant="primary" icon="plus" onClick={() => onNavigate("devices#add-device")}>
            {t("today.next.add_appliance")}
          </Button>
        )}
        {declared}
      </Panel>
    );
  }

  // « C'est lancé » : noté par le serveur pour la journée, donc sur tous les navigateurs et après
  // un nouveau calcul ; la vue relue donne l'appareil suivant, s'il y en a un.
  const markLaunched = async () => {
    setLaunchFailed(false);
    setLaunching(true);
    try {
      await declareLaunched(action.device);
      onChanged();
    } catch {
      setLaunchFailed(true);
    } finally {
      setLaunching(false);
    }
  };

  const remind = async () => {
    setFailed(false);
    try {
      await postJson("api/reminders", { device: action.device });
      setReminded(action.device);
    } catch {
      setFailed(true);
    }
  };

  // « Annuler » : l'équipement n'est plus placé aujourd'hui (feuille de la frise aussi) ; la
  // tâche reste dans la liste de Home Assistant, le calcul de demain la reprendra.
  const cancel = async () => {
    setCancelFailed(false);
    setCancelling(true);
    try {
      await cancelTask(action.device);
      onChanged();
    } catch {
      setCancelling(false);
      setCancelFailed(true);
    }
  };

  const reminder = action.reminder || reminded === action.device;
  const start = clock(action.start_min, language);
  // Heure prévue dépassée, cycle pas encore vu : on ne dit plus « à 13:00 » comme si c'était
  // à venir, ni une heure de fin qui ne vaut plus.
  const late = action.late ?? false;
  const chosen = action.chosen ?? false;
  // La raison en quelques mots (« 100 % solaire »), à côté de l'heure de fin ; la phrase
  // complète du serveur est sous « Autre heure ».
  const reason = shortReason(view.explanations.find((item) => item.device === action.device)?.explanation, t);
  return (
    <section className="ui-card ui-panel next-action" aria-labelledby="next-action-title">
      <div className="ui-panel-head">
        <p className="ui-panel-title">
          <Icon name="play" size={16} />
          {t("today.next.eyebrow")} · {late ? t("today.next.now") : start}
        </p>
      </div>
      <h3 id="next-action-title" className="next-action-title">
        {t("today.next.title", { device: action.device })}
      </h3>
      <p className="next-action-line">
        {late ? (
          // En retard, la raison dit quoi faire maintenant : elle reste sous les yeux.
          <>
            {t("today.next.slot_late", { start })}
            {action.explanation && <> {action.explanation}</>}
          </>
        ) : (
          [t("today.next.end", { end: clock(action.end_min, language) }), reason].filter(Boolean).join(" · ")
        )}
      </p>
      {action.waits_for && <p className="dim">{t("today.next.waits_for", { device: action.waits_for })}</p>}
      <div className="next-action-buttons">
        {/* Un cycle qui attend la fin d'un autre ne peut pas avoir été lancé : pas de bouton. */}
        {!action.waits_for && (
          <Button variant="primary" icon="check" disabled={launching} onClick={() => void markLaunched()}>
            {t("today.next.launched")}
          </Button>
        )}
        {action.can_remind && (
          <Button icon="bell" disabled={reminder} onClick={() => void remind()}>
            {t(reminder ? "today.next.reminder_set" : "today.next.remind")}
          </Button>
        )}
        <Button aria-expanded={otherTime || chosen} disabled={chosen} onClick={() => setOtherTime(!otherTime)}>
          {t("today.next.other_time")}
        </Button>
      </div>
      {launchFailed && <p role="alert">{t("today.next.launched_failed")}</p>}
      {failed && <p role="alert">{t("today.next.remind_failed")}</p>}
      {cancelFailed && <p role="alert">{t("today.next.cancel_failed")}</p>}
      {/* « Autre heure » : la raison complète, les autres départs et l'heure libre, l'annulation
          pour aujourd'hui. Un départ choisi garde le bloc ouvert : « Revenir au choix du calcul »
          reste visible. */}
      {(otherTime || chosen) && (
        <div className="next-action-more">
          {!late && action.explanation && <p className="dim">{action.explanation}</p>}
          <OtherStarts
            device={action.device}
            alternatives={action.alternatives ?? []}
            chosen={chosen}
            onChanged={onChanged}
            freeFrom={minuteOfDay()} // heure libre, comme la frise
          />
          {/* Annule la planification de l'équipement pour aujourd'hui, sans quitter l'écran. */}
          <Button icon="close" disabled={cancelling} onClick={() => void cancel()}>
            {t("today.next.cancel")}
          </Button>
        </div>
      )}
      {declared}
    </section>
  );
}
