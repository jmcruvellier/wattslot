// Premiers pas guidés (lot 6b.6) : tant que la mise en route n'est pas finie, quatre écrans, une
// question par écran. Connexion à Home Assistant (sautée si elle est faite), appareils trouvés
// dans le tableau Énergie (à décocher, puis enregistrés), contrat (un modèle prêt à l'emploi, ou
// plus tard), puis le premier plan, ou ce qu'il manque d'indispensable avant lui (la prévision
// solaire, par exemple). Chargé à la demande : une installation déjà en route ne le lit jamais.

import { useEffect, useState } from "react";

import { ApiError, getJson, postJson, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { buildDraft, toModel, type DraftDevice } from "../home/draft";
import type { TemplateSummary } from "../home/TemplateSection";
import type { HomeModel, HomeProposal } from "../home/types";
import Button from "../ui/Button";
import type { Setup } from "./StartScreen";

type StepKey = "connection" | "home" | "tariff" | "first_plan";
const STEPS: StepKey[] = ["connection", "home", "tariff", "first_plan"];

interface OnboardingProps {
  setup: Setup;
  running: boolean;
  onNavigate: (target: string) => void;
  onRun: () => void;
  onChanged: () => void; // relit la mise en route
}

function stateOf(setup: Setup, key: string) {
  return setup.steps.find((step) => step.key === key);
}

/** Étapes indispensables encore à faire avant le premier plan (hors connexion, maison et
 * contrat, qui ont leur écran). */
function missingBefore(setup: Setup) {
  return setup.steps.filter(
    (step) => step.required && step.state === "todo" && !(STEPS as string[]).includes(step.key),
  );
}

export default function Onboarding({ setup, running, onNavigate, onRun, onChanged }: OnboardingProps) {
  const { t } = useI18n();
  // La connexion faite n'est pas une étape à montrer.
  const steps = STEPS.filter((key) => key !== "connection" || stateOf(setup, "connection")?.state !== "done");
  const firstTodo = steps.findIndex((key) => stateOf(setup, key)?.state !== "done");
  const [index, setIndex] = useState(firstTodo < 0 ? steps.length - 1 : firstTodo);
  const current = steps[Math.min(index, steps.length - 1)];
  const missing = missingBefore(setup);
  const title = current === "first_plan" && missing.length > 0 ? "onboarding.first_plan.missing_title" : `onboarding.${current}.title`;
  const next = () => {
    onChanged();
    setIndex((value) => Math.min(value + 1, steps.length - 1));
  };

  return (
    <section className="onboarding ui-card" aria-labelledby="onboarding-title">
      <p className="ui-eyebrow">{t("onboarding.progress", { step: index + 1, count: steps.length })}</p>
      <h2 id="onboarding-title" className="ui-card-title">
        {t(title)}
      </h2>
      {current === "connection" && <ConnectionStep onNavigate={onNavigate} />}
      {current === "home" && <HomeStep onNavigate={onNavigate} onDone={next} />}
      {current === "tariff" && <TariffStep onNavigate={onNavigate} onDone={next} />}
      {current === "first_plan" && (
        <FirstPlanStep
          setup={setup}
          missing={missing}
          running={running}
          onNavigate={onNavigate}
          onRun={onRun}
        />
      )}
      <div className="onboarding-buttons">
        {index > 0 && (
          <Button variant="quiet" onClick={() => setIndex((value) => value - 1)}>
            {t("onboarding.back")}
          </Button>
        )}
        {current === "connection" && (
          <Button variant="quiet" onClick={next}>
            {t("onboarding.skip")}
          </Button>
        )}
      </div>
    </section>
  );
}

function ConnectionStep({ onNavigate }: { onNavigate: (target: string) => void }) {
  const { t } = useI18n();
  return (
    <>
      <p>{t("onboarding.connection.help")}</p>
      <Button variant="primary" onClick={() => onNavigate("connection")}>
        {t("onboarding.connection.open")}
      </Button>
    </>
  );
}

type HomeLoad =
  | { status: "loading" }
  | { status: "error"; code: "not_connected" | "failed" | "no_energy_dashboard" }
  | { status: "ready"; draft: DraftDevice[] };

/** Ce que le calcul fera de l'appareil, selon son type. */
function role(device: DraftDevice, t: (key: string, params?: Record<string, string | number>) => string): string {
  if (device.kind === "Battery" && device.capacityKwh) {
    return t("onboarding.home.kinds.battery_capacity", { kwh: device.capacityKwh.toFixed(1).replace(".", ",") });
  }
  return t(`onboarding.home.kinds.${device.kind}`);
}

function HomeStep({ onNavigate, onDone }: { onNavigate: (target: string) => void; onDone: () => void }) {
  const { t } = useI18n();
  const [load, setLoad] = useState<HomeLoad>({ status: "loading" });
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<HomeProposal>("api/home/proposals", controller.signal),
      getJson<HomeModel>("api/home", controller.signal),
    ])
      .then(([proposal, saved]) =>
        setLoad(
          proposal.energy_dashboard
            ? { status: "ready", draft: buildDraft(proposal.devices, saved) }
            : { status: "error", code: "no_energy_dashboard" },
        ),
      )
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setLoad({ status: "error", code: error instanceof ApiError && error.status === 503 ? "not_connected" : "failed" });
      });
    return () => controller.abort();
  }, []);

  if (load.status === "loading") return <p>{t("home.loading")}</p>;
  if (load.status === "error") {
    return <p role="alert">{t(load.code === "no_energy_dashboard" ? "home.no_energy_dashboard" : `home.error.${load.code}`)}</p>;
  }
  const { draft } = load;
  const toggle = (key: string, included: boolean) =>
    setLoad({ status: "ready", draft: draft.map((device) => (device.key === key ? { ...device, included } : device)) });

  const save = async () => {
    setSaving(true);
    setFailed(false);
    try {
      await putJson<HomeModel>("api/home", toModel(draft));
      onDone();
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <p>{t("onboarding.home.help")}</p>
      <ul className="onboarding-devices">
        {draft.map((device) => (
          <li key={device.key}>
            <label>
              <input type="checkbox" checked={device.included} onChange={(event) => toggle(device.key, event.target.checked)} />
              <span>
                <span className="ui-row-label">{device.name}</span>
                <span className="ui-row-help">{role(device, t)}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <p>
        <button type="button" className="link" onClick={() => onNavigate("devices#add-device")}>
          {t("onboarding.home.missing")}
        </button>
      </p>
      {failed && <p role="alert">{t("onboarding.failed")}</p>}
      <Button variant="primary" disabled={saving} onClick={() => void save()}>
        {t("onboarding.continue")}
      </Button>
    </>
  );
}

// Modèles qui demandent des entités de HA (couleur du jour, prix dynamique) : réglés dans leur
// page, pas dans les premiers pas.
const NEEDS_ENTITIES = new Set(["DayColorTariff", "DynamicTariff"]);

function TariffStep({ onNavigate, onDone }: { onNavigate: (target: string) => void; onDone: () => void }) {
  const { language, t } = useI18n();
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getJson<TemplateSummary[]>("api/templates", controller.signal)
      .then(setTemplates)
      .catch(() => setTemplates([]));
    return () => controller.abort();
  }, []);

  const local = (texts: Record<string, string>) => texts[language] ?? texts.fr ?? "";
  const template = templates?.find((found) => found.key === chosen) ?? null;

  const apply = async () => {
    if (!template) return;
    setApplying(true);
    setFailed(false);
    try {
      await postJson("api/templates/" + template.key + "/apply", {});
      onDone();
    } catch {
      setFailed(true);
    } finally {
      setApplying(false);
    }
  };

  if (templates === null) return <p>{t("onboarding.tariff.loading")}</p>;
  return (
    <>
      <p>{t("onboarding.tariff.help")}</p>
      <fieldset className="onboarding-templates">
        <legend className="visually-hidden">{t("onboarding.tariff.title")}</legend>
        {templates.map((found) => (
          <label key={found.key}>
            <input type="radio" name="template" checked={chosen === found.key} onChange={() => setChosen(found.key)} />
            <span>
              <span className="ui-row-label">{local(found.name)}</span>
              <span className="ui-row-help">{local(found.description)}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {template && NEEDS_ENTITIES.has(template.tariff_kind) && (
        <p>
          {t("onboarding.tariff.entities")}{" "}
          <button type="button" className="link" onClick={() => onNavigate("templates")}>
            {t("nav.templates")}
          </button>
        </p>
      )}
      {failed && <p role="alert">{t("onboarding.failed")}</p>}
      <div className="onboarding-buttons">
        <Button
          variant="primary"
          disabled={!template || applying || NEEDS_ENTITIES.has(template.tariff_kind)}
          onClick={() => void apply()}
        >
          {t("onboarding.tariff.apply")}
        </Button>
        <Button onClick={onDone}>{t("onboarding.tariff.later")}</Button>
      </div>
    </>
  );
}

function FirstPlanStep({
  setup,
  missing,
  running,
  onNavigate,
  onRun,
}: {
  setup: Setup;
  missing: Setup["steps"];
  running: boolean;
  onNavigate: (target: string) => void;
  onRun: () => void;
}) {
  const { t } = useI18n();
  const history = stateOf(setup, "history");
  // Une étape indispensable manque : le calcul serait refusé, on dit plutôt quoi faire.
  if (missing.length > 0) {
    return (
      <>
        <p>{t("onboarding.first_plan.missing_help")}</p>
        <ul className="onboarding-missing">
          {missing.map((step) => (
            <li key={step.key}>
              <strong>{t(`setup.steps.${step.key}`)}</strong>
              {step.reason && <p>{t(`setup.reason.${step.reason}`, step.params)}</p>}
              {step.target && (
                <Button variant="primary" onClick={() => onNavigate(step.target as string)}>
                  {t("setup.open")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      </>
    );
  }
  return (
    <>
      <p>{t("onboarding.first_plan.help")}</p>
      {history && history.state !== "done" && history.reason && (
        <p className="dim">{t(`setup.reason.${history.reason}`, history.params)}</p>
      )}
      <Button variant="primary" icon="check" disabled={running} onClick={onRun}>
        {t(running ? "setup.running" : "onboarding.first_plan.run")}
      </Button>
    </>
  );
}
