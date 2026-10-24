// Écran Aujourd'hui (lot 6b.3) : répond à « que se passe-t-il maintenant ? » et « que dois-je
// faire, et quand ? ». De haut en bas : le moment (phrase et flux du dernier quart d'heure), la
// prochaine action et ses boutons, la frise du jour, la batterie, le soleil et le bilan. La
// batterie et le soleil portent leur tendance au relevé (mesuré contre estimé). Le
// détail (onglets, courbes) reste dans Planning. Vue relue toutes les minutes.

import { useEffect, useState } from "react";

import { ApiError, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { clock, kwh, percent } from "../plan/format";
import { RUN_EVENT } from "../plan/planView";
import { IndicatorsCard } from "../plan/InsightCards";
import { TrendMark } from "../plan/SummaryCards";
import { DEFAULT_LAYOUT } from "../plan/layout";
import TimelineCard from "../plan/TimelineCard";
import OtherStarts from "../plan/OtherStarts";
import ProvisionalNote from "../plan/ProvisionalNote";
import { useHomeFeatures } from "../home/features";
import type { DayView, LineKey, NextAction, Now } from "../plan/types";
import Button from "../ui/Button";
import Card from "../ui/Card";
import StateMessage from "../ui/StateMessage";

export const REFRESH_MS = 60_000;
// « C'est lancé » : l'action reste cachée jusqu'au calcul suivant, sur ce navigateur.
export const LAUNCHED_KEY = "today.launched";

type Load = { status: "loading" } | { status: "missing" } | { status: "error" } | { status: "ready"; view: DayView };

function launchedKey(view: DayView, action: NextAction): string {
  return `${view.computed_at ?? ""}|${action.device}|${action.start_min}`;
}

function readLaunched(): string | null {
  try {
    return window.localStorage.getItem(LAUNCHED_KEY);
  } catch {
    return null;
  }
}

function readingHour(view: DayView): number | null {
  if (!view.actual_updated_at) return null;
  const at = new Date(view.actual_updated_at);
  return at.getHours() + at.getMinutes() / 60;
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
          setLoad({ status: error instanceof ApiError && error.status === 404 ? "missing" : "error" });
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

  return (
    <div className="today">
      <ProvisionalNote view={view} />
      <NowCard now={view.now ?? null} recommendation={view.recommendation} />
      <NextActionCard view={view} onChanged={() => setAttempt((count) => count + 1)} onNavigate={onNavigate} />
      <TimelineCard timeline={view.timeline} readingHour={readingHour(view)} />
      <div className="today-grid">
        {view.battery_capacity_kwh !== null && (
          <Card tone="battery" eyebrow={t("today.battery.eyebrow")} title={t("today.battery.title", {
            pct: percent(view.now?.soc_percent ?? null),
          })} meta={<TrendBadge view={view} line="soc" />}>
            <p>
              {t("today.battery.max", {
                pct: percent(view.summary.soc_max_percent),
                time: clock(view.summary.soc_max_hour * 60, language),
              })}
            </p>
            <p>{t("today.battery.end", { pct: percent(view.summary.soc_end_percent) })}</p>
          </Card>
        )}
        {view.solar !== false && (
          <Card tone="sun" eyebrow={t("today.sun.eyebrow")} title={t("today.sun.title", { kwh: kwh(view.summary.production_kwh, 1) })} meta={<TrendBadge view={view} line="production" />}>
            <p>{measuredHours ? t("today.sun.done", { kwh: kwh(produced, 1) }) : t("today.sun.none")}</p>
          </Card>
        )}
      </div>
      <IndicatorsCard view={view} layout={DEFAULT_LAYOUT.indicators} />
    </div>
  );
}

function NowCard({ now, recommendation }: { now: Now | null; recommendation: string | null }) {
  const { language, t } = useI18n();
  const flows = now !== null && now.sentence !== null;
  const tiles: { key: string; label: string; value: string; tone?: "sun" | "battery" }[] = [];
  if (flows && now) {
    if (now.production_w !== null) tiles.push({ key: "sun", label: t("today.now.panels"), value: kw(now.production_w), tone: "sun" });
    if (now.consumption_w !== null) tiles.push({ key: "home", label: t("today.now.home"), value: kw(now.consumption_w) });
    if (now.battery_w !== null || now.soc_percent !== null) {
      const parts = [now.soc_percent !== null ? `${percent(now.soc_percent)} %` : null];
      if (now.battery_w) parts.push(t(now.battery_w > 0 ? "today.now.charging" : "today.now.discharging", { kw: kw(now.battery_w) }));
      tiles.push({ key: "battery", label: t("today.now.battery"), value: parts.filter(Boolean).join(" · "), tone: "battery" });
    }
    if (now.grid_w !== null) {
      const key = now.grid_w > 0 ? "today.now.buying" : now.grid_w < 0 ? "today.now.selling" : "today.now.idle";
      tiles.push({ key: "grid", label: t("today.now.grid"), value: t(key, { kw: kw(now.grid_w) }) });
    }
  }
  return (
    <Card eyebrow={t("today.now.eyebrow")} title={flows && now?.sentence ? now.sentence : t("today.now.no_flows")}>
      {tiles.length > 0 && (
        <dl className="now-tiles">
          {tiles.map((tile) => (
            <div key={tile.key} className={tile.tone ? `now-tile now-tile-${tile.tone}` : "now-tile"}>
              <dt>{tile.label}</dt>
              <dd>{tile.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {flows && now?.since && now.until && (
        <p className="dim">
          {t("today.now.measured", {
            start: new Date(now.since).toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" }),
            end: new Date(now.until).toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" }),
          })}
        </p>
      )}
      {!flows && recommendation && <p className="recommendation">{recommendation}</p>}
    </Card>
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
  const [launched, setLaunched] = useState(readLaunched);
  const [reminded, setReminded] = useState(false);
  const [failed, setFailed] = useState(false);

  if (action === null || launched === launchedKey(view, action)) {
    // Aucun appareil placé par le calcul (tableau Énergie sans appareil) : rien ne sera jamais à
    // lancer tant qu'on n'en ajoute pas un.
    const noAppliance = features.appliances === 0;
    return (
      <Card eyebrow={t("today.next.eyebrow")} title={t(noAppliance ? "today.next.no_appliance" : "today.next.none")}>
        <p className="dim">{t(noAppliance ? "today.next.no_appliance_help" : "today.next.none_help")}</p>
        {noAppliance && onNavigate && (
          <Button variant="primary" icon="plus" onClick={() => onNavigate("devices#add-device")}>
            {t("today.next.add_appliance")}
          </Button>
        )}
      </Card>
    );
  }

  const markLaunched = () => {
    const key = launchedKey(view, action);
    try {
      window.localStorage.setItem(LAUNCHED_KEY, key);
    } catch {
      // Stockage indisponible : caché pour cette visite seulement.
    }
    setLaunched(key);
  };

  const remind = async () => {
    setFailed(false);
    try {
      await postJson("api/reminders", { device: action.device });
      setReminded(true);
    } catch {
      setFailed(true);
    }
  };

  const reminder = action.reminder || reminded;
  return (
    <section className="next-action" aria-labelledby="next-action-title">
      <p className="ui-eyebrow">
        {t("today.next.eyebrow")} · {clock(action.start_min, language)}
      </p>
      <h3 id="next-action-title" className="ui-card-title">
        {t("today.next.title", { device: action.device })}
      </h3>
      <p>
        {t("today.next.slot", { start: clock(action.start_min, language), end: clock(action.end_min, language) })}
        {action.explanation && <> {action.explanation}</>}
      </p>
      <div className="next-action-buttons">
        <Button variant="primary" icon="check" onClick={markLaunched}>
          {t("today.next.launched")}
        </Button>
        {action.can_remind && (
          <Button icon="bell" disabled={reminder} onClick={() => void remind()}>
            {t(reminder ? "today.next.reminder_set" : "today.next.remind")}
          </Button>
        )}
      </div>
      {failed && <p role="alert">{t("today.next.remind_failed")}</p>}
      <OtherStarts
        device={action.device}
        alternatives={action.alternatives ?? []}
        chosen={action.chosen ?? false}
        onChanged={onChanged}
      />
    </section>
  );
}
