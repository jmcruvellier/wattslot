// Premiers pas guidés (lot 6b.6) : tant que la mise en route n'est pas finie, quatre écrans, une
// question par écran. Connexion à Home Assistant (sautée si elle est faite), appareils trouvés
// dans le tableau Énergie (à décocher, puis enregistrés, avec l'alimentation de la maison), contrat (un modèle prêt à l'emploi, ou
// plus tard), puis le premier plan, ou ce qu'il manque d'indispensable avant lui (la prévision
// solaire, par exemple). Chargé à la demande : une installation déjà en route ne le lit jamais.

import { useEffect, useRef, useState } from "react";

import { ApiError, getJson, postJson, putJson } from "../api";
import { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import { buildDraft, firstModel, type DraftDevice } from "../home/draft";
import type { TemplateSummary } from "../home/TemplateSection";
import type { HomeModel, HomeProposal, Supply } from "../home/types";
import { kwh } from "../plan/format";
import Button from "../ui/Button";
import type { Setup } from "./StartScreen";

type StepKey = "connection" | "home" | "tariff" | "first_plan";
// Types placés au meilleur moment par le calcul : sans eux, rien à recommander.
const APPLIANCES: string[] = ["WaterHeater", "WashingMachine", "Dryer", "Dishwasher", "PoolPump"];
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
  | {
      status: "ready";
      draft: DraftDevice[];
      supply: Supply; // choix de l'utilisateur, parti de la maison enregistrée ou de la détection
      detected: boolean; // des noms de Home Assistant disent une phase
      sums: boolean | undefined; // ce que compte le compteur d'une maison déjà enregistrée
    };

const SUPPLIES: Supply[] = ["SinglePhaseSupply", "ThreePhaseSupply"];

/** Ce que le calcul fera de l'appareil, selon son type. */
function role(device: DraftDevice, t: (key: string, params?: Record<string, string | number>) => string): string {
  if (device.kind === "Battery" && device.capacityKwh) {
    return t("onboarding.home.kinds.battery_capacity", { kwh: kwh(device.capacityKwh, 1) });
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
            ? {
                status: "ready",
                draft: buildDraft(proposal.devices, saved),
                // Une maison déjà enregistrée garde son alimentation ; sinon, celle que la
                // détection propose, et le monophasé quand rien ne dit une phase.
                supply: (saved.devices.length > 0 ? saved.supply : proposal.supply) ?? "SinglePhaseSupply",
                detected: proposal.supply === "ThreePhaseSupply",
                sums: saved.devices.length > 0 ? saved.meter_sums_phases : undefined,
              }
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
  const { draft, supply, detected, sums } = load;
  const toggle = (key: string, included: boolean) =>
    setLoad({ ...load, draft: draft.map((device) => (device.key === key ? { ...device, included } : device)) });

  const save = async () => {
    setSaving(true);
    setFailed(false);
    try {
      const model = firstModel(draft, supply);
      await putJson<HomeModel>("api/home", sums === undefined ? model : { ...model, meter_sums_phases: sums });
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
      {/* Aucun appareil à placer dans le tableau Énergie : sans en ajouter un, WattSlot n'aura
          rien à recommander ; on le dit, et l'ajout devient un vrai bouton. */}
      {draft.some((device) => device.included && APPLIANCES.includes(device.kind)) ? (
        <p>
          <button type="button" className="link" onClick={() => onNavigate("devices#add-device")}>
            {t("onboarding.home.missing")}
          </button>
        </p>
      ) : (
        <div className="onboarding-no-appliance">
          <p>{t("onboarding.home.no_appliance")}</p>
          <Button icon="plus" onClick={() => onNavigate("devices#add-device")}>
            {t("today.next.add_appliance")}
          </Button>
        </div>
      )}
      {/* Alimentation : demandée ici, sinon une maison en triphasé reste réglée en monophasé
          sans que rien ne le dise. La phase de chaque appareil se règle ensuite, dans sa fiche. */}
      <div className="onboarding-supply">
        <label>
          {t("supply.kind")}{" "}
          <select value={supply} onChange={(event) => setLoad({ ...load, supply: event.target.value as Supply })}>
            {SUPPLIES.map((kind) => (
              <option key={kind} value={kind}>
                {t(`supply.kinds.${kind}`)}
              </option>
            ))}
          </select>
        </label>
        <Hint text={t("supply.kind_hint")} />
        {detected && <p role="note">{t("onboarding.home.supply_detected")}</p>}
        {supply === "ThreePhaseSupply" && <p>{t("onboarding.home.three_phase")}</p>}
      </div>
      {failed && <p role="alert">{t("onboarding.failed")}</p>}
      <Button variant="primary" disabled={saving} onClick={() => void save()}>
        {t("onboarding.continue")}
      </Button>
    </>
  );
}

// Modèle au prix dynamique : ses entités se règlent dans la page des modèles. Le jour annoncé
// (Tempo, EJP) se choisit ici, parmi les entités de HA qui lui ressemblent.
const NEEDS_ENTITIES = new Set(["DynamicTariff"]);
const ANNOUNCED_DAY = "DayColorTariff";
const OTHER = "__other__";

interface DayEntity {
  entity_id: string;
  name: string | null;
  state: string | null;
  tomorrow: boolean; // son nom parle du lendemain
}

interface DayEntities {
  color_entity: string;
  color_tomorrow_entity: string;
}

const NO_ENTITIES: DayEntities = { color_entity: "", color_tomorrow_entity: "" };

function TariffStep({ onNavigate, onDone }: { onNavigate: (target: string) => void; onDone: () => void }) {
  const { language, t } = useI18n();
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<DayEntity[] | null>(null);
  const [entities, setEntities] = useState<DayEntities>(NO_ENTITIES);
  const [applying, setApplying] = useState(false);
  const [failed, setFailed] = useState(false);
  const latest = useRef<string | null>(null); // modèle choisi en dernier (réponses en retard)

  useEffect(() => {
    const controller = new AbortController();
    getJson<TemplateSummary[]>("api/templates", controller.signal)
      .then(setTemplates)
      .catch(() => setTemplates([]));
    return () => controller.abort();
  }, []);

  const local = (texts: Record<string, string>) => texts[language] ?? texts.fr ?? "";
  const template = templates?.find((found) => found.key === chosen) ?? null;
  const announced = template?.tariff_kind === ANNOUNCED_DAY;

  // Jour annoncé : les entités candidates, la première du jour et la première du lendemain
  // proposées d'office (modifiables).
  const choose = (found: TemplateSummary) => {
    setChosen(found.key);
    latest.current = found.key;
    setFailed(false);
    setEntities(NO_ENTITIES);
    setCandidates(null);
    if (found.tariff_kind !== ANNOUNCED_DAY) return;
    getJson<DayEntity[]>(`api/templates/${found.key}/entities`)
      .then((listed) => {
        if (latest.current !== found.key) return;
        setCandidates(listed);
        setEntities({
          color_entity: listed.find((entity) => !entity.tomorrow)?.entity_id ?? "",
          color_tomorrow_entity: listed.find((entity) => entity.tomorrow)?.entity_id ?? "",
        });
      })
      .catch(() => {
        if (latest.current === found.key) setCandidates([]);
      });
  };

  const apply = async () => {
    if (!template) return;
    setApplying(true);
    setFailed(false);
    const body = announced
      ? Object.fromEntries(Object.entries(entities).filter(([, value]) => value))
      : {};
    try {
      await postJson("api/templates/" + template.key + "/apply", body);
      onDone();
    } catch {
      setFailed(true);
    } finally {
      setApplying(false);
    }
  };

  if (templates === null) return <p>{t("onboarding.tariff.loading")}</p>;
  const blocked =
    !template ||
    applying ||
    NEEDS_ENTITIES.has(template.tariff_kind) ||
    (announced && (candidates === null || !entities.color_entity));
  return (
    <>
      <p>{t("onboarding.tariff.help")}</p>
      <fieldset className="onboarding-templates">
        <legend className="visually-hidden">{t("onboarding.tariff.title")}</legend>
        {templates.map((found) => (
          <label key={found.key}>
            <input type="radio" name="template" checked={chosen === found.key} onChange={() => choose(found)} />
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
      {announced && candidates !== null && (
        <div className="onboarding-day-entities">
          {candidates.length === 0 && <p>{t("onboarding.tariff.no_candidate")}</p>}
          <DayEntityField
            key={`${chosen}-today`}
            label={t("tariff.color_entity")}
            value={entities.color_entity}
            candidates={candidates}
            onChange={(color_entity) => setEntities({ ...entities, color_entity })}
          />
          <Hint text={t("tariff.color_entity_hint")} />
          <DayEntityField
            key={`${chosen}-tomorrow`}
            label={t("tariff.color_tomorrow_entity")}
            value={entities.color_tomorrow_entity}
            candidates={candidates}
            optional
            onChange={(color_tomorrow_entity) => setEntities({ ...entities, color_tomorrow_entity })}
          />
        </div>
      )}
      {failed && <p role="alert">{t("onboarding.failed")}</p>}
      <div className="onboarding-buttons">
        <Button variant="primary" disabled={blocked} onClick={() => void apply()}>
          {t("onboarding.tariff.apply")}
        </Button>
        <Button onClick={onDone}>{t("onboarding.tariff.later")}</Button>
      </div>
    </>
  );
}

// Choix d'une entité du jour annoncé : une des candidates, ou un identifiant saisi (« Autre
// entité… », ou d'office quand HA n'en propose aucune).
function DayEntityField({
  label,
  value,
  candidates,
  optional = false,
  onChange,
}: {
  label: string;
  value: string;
  candidates: DayEntity[];
  optional?: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  const [typing, setTyping] = useState(candidates.length === 0);
  const describe = (entity: DayEntity) =>
    `${entity.name ? `${entity.name} — ` : ""}${entity.entity_id}${entity.state ? ` (${entity.state})` : ""}`;
  return (
    <p className="onboarding-day-entity">
      {candidates.length > 0 && (
        <label>
          {label}{" "}
          <select
            value={typing ? OTHER : value}
            onChange={(event) => {
              const chosen = event.target.value;
              setTyping(chosen === OTHER);
              onChange(chosen === OTHER ? "" : chosen);
            }}
          >
            {optional && <option value="">{t("onboarding.tariff.none")}</option>}
            {!optional && value === "" && !typing && <option value="" disabled />}
            {candidates.map((entity) => (
              <option key={entity.entity_id} value={entity.entity_id}>
                {describe(entity)}
              </option>
            ))}
            <option value={OTHER}>{t("onboarding.tariff.other_entity")}</option>
          </select>
        </label>
      )}
      {typing && (
        <label>
          {candidates.length > 0 ? t("onboarding.tariff.entity_id") : label}{" "}
          <input
            value={value}
            placeholder="sensor.…"
            onChange={(event) => onChange(event.target.value.trim())}
          />
        </label>
      )}
    </p>
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
      {/* Sans batterie (étape « sans objet »), la phrase n'en parle pas. */}
      <p>
        {t(
          stateOf(setup, "battery")?.state === "not_applicable"
            ? "onboarding.first_plan.help_no_battery"
            : "onboarding.first_plan.help",
        )}
      </p>
      {history && history.state !== "done" && history.reason && (
        <p className="dim">{t(`setup.reason.${history.reason}`, history.params)}</p>
      )}
      <Button variant="primary" icon="check" disabled={running} onClick={onRun}>
        {t(running ? "setup.running" : "onboarding.first_plan.run")}
      </Button>
    </>
  );
}
