// Onglet « Données » de Ma maison (qualité des données) : les valeurs des compteurs corrigées
// (automatiquement ou à la main), les trous des sept derniers jours, l'analyse d'une période,
// les corrections annulées. Chaque correction s'ouvre dans sa feuille, en phrases, avec les
// autres corrections possibles. Chargé à la demande : son propre fichier.

import { useEffect, useState } from "react";

import { ApiError, deleteRequest, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber, type Language } from "../i18n/translate";
import Button from "../ui/Button";
import Sheet from "../ui/Sheet";
import SettingRow, { SettingList } from "../ui/SettingRow";
import StateMessage from "../ui/StateMessage";
import type { HomeData } from "./HomeSummary";

type Kind = "spike" | "negative" | "gap";
type Method = "discard" | "estimate" | "raw";

// API du serveur (quality.py, corrections.py).
export interface Correction {
  id: number;
  entity_id: string;
  period: string;
  start: string;
  kind: Kind;
  method: Method;
  original_kwh: number | null;
  corrected_kwh: number | null;
  automatic: boolean;
  created_at: string;
  undone_at: string | null;
}

interface Anomaly {
  entity_id: string;
  device: string;
  period: string;
  start: string;
  kind: Kind;
  energy_kwh: number | null;
  missing: number;
  correction: Correction | null;
}

interface QualityStatus {
  running: boolean;
  last_run_at: string | null;
}

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; corrections: Correction[]; undone: Correction[]; gaps: Anomaly[]; checked: string | null };

const HOUR = "PT1H";
const GAPS_DAYS = 7;
const METHODS: Method[] = ["raw", "estimate", "discard"];

function kwh(language: Language, value: number): string {
  return `${formatNumber(language, value, Math.abs(value) < 10 ? 2 : 0)} kWh`;
}

// « 20/10, 0:00 – 1:00 » dans l'heure du navigateur (celle de la maison).
function periodText(language: Language, period: string, start: string): string {
  const from = new Date(start);
  const to = new Date(from.getTime() + (period === HOUR ? 60 : 15) * 60_000);
  const day = from.toLocaleDateString(language, { day: "2-digit", month: "2-digit" });
  const time = (d: Date) => d.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });
  return `${day}, ${time(from)} – ${time(to)}`;
}

// Nom d'un compteur : son appareil, et son rôle quand l'appareil en a plusieurs (son entité quand
// deux ont le même rôle : heures creuses et pleines d'un Linky).
function useSensorName(data: HomeData) {
  const { t } = useI18n();
  return (entityId: string) => {
    const device = data.devices.find((d) => d.sensors.some((s) => s.entity_id === entityId));
    if (!device) return entityId;
    const sensor = device.sensors.find((s) => s.entity_id === entityId)!;
    const counters = device.sensors.filter((s) => s.role.startsWith("Energy"));
    if (counters.length < 2) return device.name;
    const same = counters.filter((s) => s.role === sensor.role).length > 1;
    return `${device.name} · ${same ? entityId : t(`role.${sensor.role}`)}`;
  };
}

export default function DataTab({ data }: { data: HomeData }) {
  const { language, t } = useI18n();
  const name = useSensorName(data);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0); // relecture après une correction ou une analyse
  const [open, setOpen] = useState<Correction | null>(null);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    let active = true;
    const now = new Date();
    const since = new Date(now.getTime() - GAPS_DAYS * 86_400_000);
    Promise.all([
      getJson<Correction[]>("api/quality/corrections?undone=true"),
      getJson<QualityStatus>("api/quality/status"),
      // Trous des derniers jours, heure par heure (les sauts y sont aussi corrigés).
      postJson<{ anomalies: Anomaly[] }>("api/quality/scan", {
        start: since.toISOString(),
        end: now.toISOString(),
        periods: [HOUR],
      }),
    ])
      .then(([all, status, scan]) => {
        if (!active) return;
        setLoad({
          status: "ready",
          corrections: all.filter((c) => c.undone_at === null),
          undone: all.filter((c) => c.undone_at !== null),
          gaps: scan.anomalies.filter((a) => a.kind === "gap"),
          checked: status.last_run_at,
        });
      })
      .catch(() => active && setLoad({ status: "error" }));
    return () => {
      active = false;
    };
  }, [attempt]);

  const reload = () => setAttempt((count) => count + 1);

  if (load.status === "loading") return <StateMessage kind="loading" title={t("quality.loading")} />;
  if (load.status === "error") {
    return <StateMessage kind="error" title={t("quality.error.load")} onRetry={reload} />;
  }

  const { corrections, undone, checked } = load;

  // Trous regroupés par compteur : heures manquantes et première.
  const gaps = new Map<string, { missing: number; since: string }>();
  for (const gap of load.gaps) {
    const known = gaps.get(gap.entity_id);
    gaps.set(gap.entity_id, {
      missing: (known?.missing ?? 0) + gap.missing,
      since: known && known.since < gap.start ? known.since : gap.start,
    });
  }
  const day = (start: string) => new Date(start).toLocaleDateString(language, { day: "2-digit", month: "2-digit" });
  const valueText = (c: Correction) =>
    `${c.original_kwh === null ? "—" : kwh(language, c.original_kwh)} → ${
      c.corrected_kwh === null ? t("quality.discarded") : kwh(language, c.corrected_kwh)
    }`;
  const rows = (list: Correction[]) => (
    <SettingList>
      {list.map((c) => (
        <SettingRow
          key={c.id}
          label={name(c.entity_id)}
          description={`${periodText(language, c.period, c.start)} · ${valueText(c)}`}
          onOpen={() => setOpen(c)}
        />
      ))}
    </SettingList>
  );

  return (
    <>
      <div className={corrections.length > 0 ? "card quality-summary" : "card quality-summary quality-clean"}>
        <strong>
          {corrections.length > 0
            ? t("quality.summary.corrected", { count: corrections.length })
            : t("quality.summary.clean")}
        </strong>
        <small>
          {checked
            ? t("quality.summary.checked", {
                time: new Date(checked).toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" }),
              })
            : t("quality.summary.not_checked")}
        </small>
      </div>

      {corrections.length > 0 && (
        <>
          <h3 className="home-summary-heading">{t("quality.corrected")}</h3>
          {rows(corrections)}
        </>
      )}

      {gaps.size > 0 && (
        <>
          <h3 className="home-summary-heading">{t("quality.gaps")}</h3>
          <SettingList>
            {[...gaps].map(([entityId, gap]) => (
              <SettingRow
                key={entityId}
                label={name(entityId)}
                description={t("quality.gap", { count: gap.missing, date: day(gap.since) })}
              />
            ))}
          </SettingList>
          <p className="dim">{t("quality.gaps_help")}</p>
        </>
      )}

      <p>
        <Button icon="target" onClick={() => setScanning(true)}>
          {t("quality.scan.open")}
        </Button>
      </p>

      {undone.length > 0 && (
        <details>
          <summary>{t("quality.undone", { count: undone.length })}</summary>
          {rows(undone)}
        </details>
      )}

      {open && (
        <CorrectionSheet
          correction={open}
          title={name(open.entity_id)}
          period={periodText(language, open.period, open.start)}
          onClose={() => setOpen(null)}
          onDone={() => {
            setOpen(null);
            reload();
          }}
        />
      )}
      {scanning && (
        <ScanSheet
          data={data}
          name={name}
          onClose={() => setScanning(false)}
          onScanned={reload}
        />
      )}
    </>
  );
}

// Feuille d'une correction : ce qui s'est passé, ce qui a été fait, les autres choix.
function CorrectionSheet({
  correction,
  title,
  period,
  onClose,
  onDone,
}: {
  correction: Correction;
  title: string;
  period: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { language, t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = correction.undone_at === null;
  const value = correction.original_kwh === null ? "—" : kwh(language, correction.original_kwh);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onDone();
    } catch (failure) {
      const code = failure instanceof ApiError && typeof failure.detail === "string" ? failure.detail : "failed";
      setError(["no_raw", "no_neighbours"].includes(code) ? code : "failed");
      setBusy(false);
    }
  };

  const apply = (method: Method) =>
    run(() =>
      postJson("api/quality/corrections", {
        entity_id: correction.entity_id,
        period: correction.period,
        start: correction.start,
        method,
      }),
    );

  return (
    <Sheet open title={title} onClose={onClose}>
      <p>
        <strong>{period}</strong>
      </p>
      <p>{t(`quality.kind.${correction.kind}`, { value })}</p>
      <p className="dim">
        {active
          ? `${t(correction.automatic ? "quality.automatic" : "quality.manual")} ${t(`quality.method.${correction.method}`, {
              value: correction.corrected_kwh === null ? "" : kwh(language, correction.corrected_kwh),
            })}`
          : t("quality.was_undone")}
      </p>
      <h3 className="home-summary-heading">{t(active ? "quality.actions" : "quality.actions_again")}</h3>
      <p className="home-devices-actions">
        {METHODS.filter((method) => !active || method !== correction.method).map((method) => (
          <Button key={method} disabled={busy} onClick={() => void apply(method)}>
            {t(`quality.action.${method}`)}
          </Button>
        ))}
        {active && (
          <Button
            variant="quiet"
            disabled={busy}
            onClick={() => void run(() => deleteRequest(`api/quality/corrections/${correction.id}`))}
          >
            {t("quality.action.undo")}
          </Button>
        )}
      </p>
      {error && <p role="alert">{t(`quality.error.${error}`)}</p>}
    </Sheet>
  );
}

// Analyse d'une période : un compteur ou tous, du … au … (jours entiers, heure du navigateur).
function ScanSheet({
  data,
  name,
  onClose,
  onScanned,
}: {
  data: HomeData;
  name: (entityId: string) => string;
  onClose: () => void;
  onScanned: () => void;
}) {
  const { t } = useI18n();
  const today = new Date();
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const counters = data.devices.flatMap((d) => d.sensors.filter((s) => s.role.startsWith("Energy")).map((s) => s.entity_id));
  const [entity, setEntity] = useState("");
  const [from, setFrom] = useState(iso(new Date(today.getTime() - 7 * 86_400_000)));
  const [to, setTo] = useState(iso(today));
  const [result, setResult] = useState<{ count: number } | "failed" | "running" | null>(null);

  const onRun = async () => {
    setResult("running");
    const start = new Date(`${from}T00:00:00`);
    const end = new Date(new Date(`${to}T00:00:00`).getTime() + 86_400_000);
    try {
      const found = await postJson<{ anomalies: Anomaly[] }>("api/quality/scan", {
        start: start.toISOString(),
        end: end.toISOString(),
        entity_ids: entity ? [entity] : null,
      });
      setResult({ count: found.anomalies.filter((a) => a.kind !== "gap").length });
      onScanned();
    } catch {
      setResult("failed");
    }
  };

  return (
    <Sheet open title={t("quality.scan.title")} onClose={onClose}>
      <div className="expert-form">
        <label>
          {t("quality.scan.sensor")}{" "}
          <select value={entity} onChange={(event) => setEntity(event.target.value)}>
            <option value="">{t("quality.scan.all")}</option>
            {counters.map((id) => (
              <option key={id} value={id}>
                {name(id)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("quality.scan.from")} <input type="date" value={from} max={to} onChange={(event) => setFrom(event.target.value)} />
        </label>
        <label>
          {t("quality.scan.to")} <input type="date" value={to} min={from} onChange={(event) => setTo(event.target.value)} />
        </label>
      </div>
      <div className="home-sheet-actions">
        {result === "failed" && <p role="alert">{t("quality.scan.failed")}</p>}
        {result !== null && typeof result === "object" && (
          <p role="status">
            {result.count === 0 ? t("quality.scan.none") : t("quality.scan.found", { count: result.count })}
          </p>
        )}
        <Button variant="primary" disabled={result === "running" || !from || !to} onClick={() => void onRun()}>
          {t("quality.scan.run")}
        </Button>
      </div>
    </Sheet>
  );
}
