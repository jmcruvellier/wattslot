// Accueil (lot 4.1, écran Aujourd'hui au lot 6b.3) : la mise en route tant qu'elle n'est pas
// finie, puis l'écran Aujourd'hui (``TodayView``), la mise en route restante repliée en tête. Les
// étapes sont calculées par l'application (/api/setup) : faite, à faire, en cours, impossible pour
// l'instant ; chacune renvoie au formulaire où la régler. Rien ne bloque (décision 1).

import { lazy, Suspense, useEffect, useState } from "react";

import { getJson } from "../api";
import Glossary from "../common/Glossary";
import { connectionErrorParams } from "../connection/service";
import { DEFAULT_PRICE_EUR_KWH } from "../home/configuration";
import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { refreshStatus } from "../nav/status";
import TodayView from "../today/TodayView";
import StateMessage from "../ui/StateMessage";

// Premiers pas guidés : une installation déjà en route ne les charge jamais.
const Onboarding = lazy(() => import("./Onboarding"));

export interface SetupStep {
  key: string;
  state: "done" | "todo" | "waiting" | "blocked" | "not_applicable";
  required: boolean;
  reason: string | null;
  params: Record<string, string>;
  target: string | null; // page de l'interface, ancre comprise (« home#tariff »)
}

export interface Setup {
  steps: SetupStep[];
  ready: boolean;
}

type Load = { status: "loading" } | { status: "ready"; setup: Setup } | { status: "error" };

const MARKS: Record<SetupStep["state"], string> = {
  done: "✓",
  todo: "○",
  waiting: "…",
  blocked: "–",
  not_applicable: "·",
};

export default function StartScreen({ onNavigate }: { onNavigate: (target: string) => void }) {
  const { t } = useI18n();
  const { perKwh } = useCurrency();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [version, setVersion] = useState(0);
  const [running, setRunning] = useState(false);
  const [failed, setFailed] = useState(false); // calcul refusé (étape indispensable manquante…)

  useEffect(() => {
    const controller = new AbortController();
    getJson<Setup>("api/setup", controller.signal)
      .then((setup) => setLoad({ status: "ready", setup }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [version]);

  const runNow = async () => {
    setRunning(true);
    setFailed(false);
    try {
      const response = await fetch("api/planning/run", { method: "POST" });
      if (!response.ok) setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setRunning(false);
      setVersion((count) => count + 1);
      refreshStatus();
    }
  };

  if (load.status === "loading") return <StateMessage kind="loading" title={t("setup.loading")} />;
  if (load.status === "error") {
    return (
      <StateMessage
        kind="error"
        title={t("setup.error")}
        onRetry={() => {
          setLoad({ status: "loading" });
          setVersion((count) => count + 1);
        }}
      />
    );
  }
  const { setup } = load;
  const steps = setup.steps.filter((step) => step.state !== "not_applicable");
  const left = steps.filter((step) => step.state !== "done").length;

  const list = (
    <ol className="setup">
      {steps.map((step) => (
        <li key={step.key} aria-label={t(`setup.steps.${step.key}`)} data-state={step.state}>
          <span aria-hidden="true">{MARKS[step.state]}</span> <strong>{t(`setup.steps.${step.key}`)}</strong>
          {step.required && step.state !== "done" && <> — {t("setup.required")}</>}{" "}
          <span>{t(`setup.states.${step.state}`)}</span>
          {step.reason && (
            <p>
              {t(`setup.reason.${step.reason}`, {
                ...connectionErrorParams(t, step.params),
                price: perKwh(DEFAULT_PRICE_EUR_KWH),
              })}
            </p>
          )}
          {step.state !== "done" && step.target && (
            <button type="button" onClick={() => onNavigate(step.target as string)}>
              {t("setup.open")}
            </button>
          )}
          {step.key === "first_plan" && step.state === "todo" && (
            <button type="button" disabled={running} onClick={() => void runNow()}>
              {t(running ? "setup.running" : "setup.run_now")}
            </button>
          )}
        </li>
      ))}
    </ol>
  );

  // Premiers pas guidés (lot 6b.6), la liste détaillée des étapes repliée dessous.
  if (!setup.ready) {
    return (
      <section aria-labelledby="setup-title">
        <h2 id="setup-title" className="visually-hidden">
          {t("setup.title")}
        </h2>
        {failed && <p role="alert">{t("setup.run_failed")}</p>}
        <Suspense fallback={<p>{t("setup.loading")}</p>}>
          <Onboarding
            setup={setup}
            running={running}
            onNavigate={onNavigate}
            onRun={() => void runNow()}
            onChanged={() => setVersion((count) => count + 1)}
          />
        </Suspense>
        <details className="plan-more">
          <summary>{t("onboarding.all_steps")}</summary>
          <p>{t("setup.intro")}</p>
          {list}
          <button type="button" onClick={() => setVersion((count) => count + 1)}>
            {t("setup.refresh")}
          </button>
        </details>
        <Glossary />
      </section>
    );
  }
  return (
    <>
      {left > 0 && (
        <details className="ui-card setup-card">
          <summary>{t("setup.some_left", { count: left })}</summary>
          {list}
        </details>
      )}
      <TodayView onNavigate={onNavigate} />
      <Glossary />
    </>
  );
}
