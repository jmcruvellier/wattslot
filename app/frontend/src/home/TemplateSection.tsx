// « Partir d'un modèle » (lot 4.3) : un modèle prêt à l'emploi règle les comportements par type
// d'équipement, le tarif et l'objectif de la maison enregistrée, après un aperçu de ce qui
// change. Les entités du tarif (couleur Tempo, prix dynamique) sont propres à chaque maison : on
// les demande pour les modèles qui en ont besoin.

import { useEffect, useState } from "react";

import { ApiError, getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import type { Configuration, ConfigurationIssue, TariffKind } from "./configuration";
import type { HomeModel } from "./types";

export interface TemplateSummary {
  key: string;
  name: Record<string, string>;
  description: Record<string, string>;
  tariff_kind: TariffKind;
  devices: string[];
}

interface Change {
  part: "device" | "tariff" | "objective" | "battery";
  device: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

interface Preview {
  template: string;
  changes: Change[];
  issues: ConfigurationIssue[];
}

type Entities = Partial<Record<"color_entity" | "color_tomorrow_entity" | "price_entity" | "export_entity", string>>;

// Entités demandées selon le type de tarif du modèle.
const ENTITY_FIELDS: Partial<Record<TariffKind, (keyof Entities)[]>> = {
  DayColorTariff: ["color_entity", "color_tomorrow_entity"],
  DynamicTariff: ["price_entity", "export_entity"],
};

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; templates: TemplateSummary[]; home: HomeModel; configuration: Configuration };

type Apply = "idle" | "applying" | "applied" | "failed";

export default function TemplateSection({ version, onApplied }: { version: number; onApplied: () => void }) {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [chosen, setChosen] = useState<string | null>(null);
  const [entities, setEntities] = useState<Entities>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [apply, setApply] = useState<Apply>("idle");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<TemplateSummary[]>("api/templates", controller.signal),
      getJson<HomeModel>("api/home", controller.signal),
      getJson<Configuration>("api/configuration", controller.signal),
    ])
      .then(([templates, home, configuration]) => setLoad({ status: "ready", templates, home, configuration }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [version]);

  if (load.status === "loading") return null;
  if (load.status === "error") return <p role="alert">{t("templates.error")}</p>;
  const { templates, home, configuration } = load;
  const names = new Map(home.devices.map((device) => [device.key, device.name]));
  const local = (texts: Record<string, string>) => texts[language] ?? texts.fr ?? "";
  const template = templates.find((found) => found.key === chosen) ?? null;
  const fields = template ? (ENTITY_FIELDS[template.tariff_kind] ?? []) : [];

  const choose = (key: string) => {
    const found = templates.find((candidate) => candidate.key === key);
    const tariff = configuration.tariff;
    // Les entités du tarif enregistré, s'il est du même type que celui du modèle.
    const kept: Entities = {};
    if (found && tariff && tariff.kind === found.tariff_kind) {
      for (const field of ENTITY_FIELDS[found.tariff_kind] ?? []) {
        if (tariff[field]) kept[field] = tariff[field] as string;
      }
    }
    setChosen(key);
    setEntities(kept);
    setPreview(null);
    setApply("idle");
  };

  const body = () => Object.fromEntries(Object.entries(entities).filter(([, value]) => value));

  const onPreview = async () => {
    if (!template) return;
    setApply("idle");
    try {
      setPreview(await postJson<Preview>(`api/templates/${template.key}/preview`, body()));
    } catch {
      setApply("failed");
    }
  };

  const onApply = async () => {
    if (!template) return;
    setApply("applying");
    try {
      await postJson<Configuration>(`api/templates/${template.key}/apply`, body());
      setApply("applied");
      setPreview(null);
      onApplied();
    } catch (error) {
      if (error instanceof ApiError && error.status === 422 && Array.isArray(error.detail)) {
        setPreview((current) => current && { ...current, issues: error.detail as ConfigurationIssue[] });
      }
      setApply("failed");
    }
  };

  const describe = (change: Change): string => {
    if (change.part !== "device") return t(`templates.change.${change.part}`);
    const name = names.get(change.device ?? "") ?? change.device ?? "";
    const before = change.before?.behavior as string | undefined;
    const after = change.after?.behavior as string | undefined;
    if (before && after && before !== after) {
      return t("templates.change.behavior", {
        device: name,
        before: t(`behavior.${before}`),
        after: t(`behavior.${after}`),
      });
    }
    return t("templates.change.settings", { device: name });
  };

  return (
    <section aria-labelledby="models">
      <h2 className="visually-hidden" id="models">{t("templates.title")}</h2>
      <p>{t("templates.intro")}</p>
      {home.devices.length === 0 ? (
        <p>{t("templates.no_home")}</p>
      ) : (
        <>
          <fieldset>
            <legend>{t("templates.choose")}</legend>
            {templates.map((found) => (
              <div key={found.key}>
                <label>
                  <input
                    type="radio"
                    name="template"
                    value={found.key}
                    checked={chosen === found.key}
                    onChange={() => choose(found.key)}
                  />{" "}
                  <strong>{local(found.name)}</strong>
                </label>
                <p>{local(found.description)}</p>
                <p>
                  {found.devices.length === 0
                    ? t("templates.no_devices")
                    : t("templates.devices", {
                        devices: found.devices.map((key) => names.get(key) ?? key).join(", "),
                      })}
                </p>
              </div>
            ))}
          </fieldset>
          {template && (
            <>
              {fields.map((field) => (
                <p key={field}>
                  <label>
                    {t(`tariff.${field}`)}{" "}
                    <input
                      value={entities[field] ?? ""}
                      placeholder="sensor.…"
                      onChange={(event) => {
                        setPreview(null);
                        setEntities({ ...entities, [field]: event.target.value.trim() });
                      }}
                    />
                  </label>
                </p>
              ))}
              <button type="button" onClick={() => void onPreview()}>
                {t("templates.preview")}
              </button>
            </>
          )}
          {preview && template && (
            <div aria-label={t("templates.preview_title")}>
              <h3>{t("templates.preview_title")}</h3>
              {preview.changes.length === 0 ? (
                <p>{t("templates.nothing")}</p>
              ) : (
                <ul>
                  {preview.changes.map((change, index) => (
                    <li key={`${change.part}-${change.device ?? index}`}>{describe(change)}</li>
                  ))}
                </ul>
              )}
              {preview.issues.length > 0 && (
                <ul role="alert">
                  {preview.issues.map((issue, index) => (
                    <li key={`${issue.code}-${index}`} className="issue">
                      {t(`configuration.issue.${issue.code}`, {
                        ...issue.params,
                        device: names.get(issue.device ?? "") ?? issue.device ?? "",
                      })}
                    </li>
                  ))}
                </ul>
              )}
              <p>{t("templates.keep")}</p>
              <button
                type="button"
                disabled={preview.issues.length > 0 || preview.changes.length === 0 || apply === "applying"}
                onClick={() => void onApply()}
              >
                {t("templates.apply")}
              </button>
            </div>
          )}
          {apply === "applied" && <p role="status">{t("templates.applied")}</p>}
          {apply === "failed" && <p role="alert">{t("templates.failed")}</p>}
        </>
      )}
    </section>
  );
}
