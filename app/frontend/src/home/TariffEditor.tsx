// Tarif de la maison (lot 3.2) : prix unique, heures creuses et pleines, couleur du jour (Tempo)
// ou prix dynamique lu dans HA ; prix de revente fixe ou lu dans une entité. Proposition d'après
// les prix déclarés dans le tableau Énergie de HA. Les plages limitées à certains jours ou mois se
// règlent par l'API ; elles sont signalées ici.

import { useState } from "react";

import { ApiError, getJson } from "../api";
import Advanced, { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import {
  DEFAULT_PRICE_EUR_KWH,
  PRICE_UNITS,
  TARIFF_KINDS,
  TARIFF_TEMPLATES,
  type ColorPrices,
  type PriceBand,
  type Tariff,
  type TariffKind,
} from "./configuration";

const HOURS = Array.from({ length: 25 }, (_, hour) => hour);

// Contrat (lot 7.3) : abonnement mensuel et puissance souscrite, quel que soit le tarif.
function Contract({ tariff, onChange }: { tariff: Tariff; onChange: (tariff: Tariff) => void }) {
  const { t } = useI18n();
  return (
    <>
      <p>
        <label>
          {t("tariff.subscription")}{" "}
          <input
            type="number"
            min="0"
            step="0.01"
            value={tariff.subscription_eur_month}
            onChange={(event) =>
              onChange({ ...tariff, subscription_eur_month: event.target.value === "" ? 0 : Number(event.target.value) })
            }
          />{" "}
          {t("tariff.per_month")}
        </label>
        <Hint text={t("tariff.subscription_hint")} />
      </p>
      <p>
        <label>
          {t("tariff.contract_kva")}{" "}
          <input
            type="number"
            min="0.1"
            step="0.1"
            value={tariff.contract_kva ?? ""}
            onChange={(event) =>
              onChange({ ...tariff, contract_kva: event.target.value === "" ? null : Number(event.target.value) })
            }
          />{" "}
          kVA
        </label>
        <Hint text={t("tariff.contract_kva_hint")} />
      </p>
    </>
  );
}

function Price({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label>
      {label}{" "}
      <input
        type="number"
        min="0"
        step="0.000001"
        value={value}
        onChange={(event) => onChange(event.target.value === "" ? 0 : Number(event.target.value))}
      />{" "}
      €/kWh
    </label>
  );
}

function Hour({ label, value, from, to, onChange }: {
  label: string;
  value: number;
  from: number;
  to: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      {label}{" "}
      <select value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {HOURS.filter((hour) => hour >= from && hour <= to).map((hour) => (
          <option key={hour} value={hour}>
            {hour} h
          </option>
        ))}
      </select>
    </label>
  );
}

function Entity({ label, value, onChange }: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <label>
      {label}{" "}
      <input
        placeholder="sensor.…"
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value.trim() === "" ? null : event.target.value.trim())}
      />
    </label>
  );
}

function BandsEditor({ bands, fallback, label, onChange }: {
  bands: PriceBand[];
  fallback: number;
  label: string; // préfixe des noms accessibles des plages
  onChange: (bands: PriceBand[]) => void;
}) {
  const { t } = useI18n();
  const setBand = (index: number, change: Partial<PriceBand>) =>
    onChange(bands.map((band, i) => (i === index ? { ...band, ...change } : band)));
  return (
    <ul>
      {bands.map((band, index) => (
        <li key={index} aria-label={`${label}${t("tariff.band", { number: index + 1 })}`}>
          <Hour label={t("tariff.from")} value={band.start_hour} from={0} to={23} onChange={(start_hour) => setBand(index, { start_hour })} />{" "}
          <Hour label={t("tariff.to")} value={band.end_hour} from={1} to={24} onChange={(end_hour) => setBand(index, { end_hour })} />{" "}
          <Price label={t("tariff.price")} value={band.eur_kwh} onChange={(eur_kwh) => setBand(index, { eur_kwh })} />{" "}
          {(band.weekdays.length > 0 || band.months.length > 0) && <em>{t("tariff.limited")}</em>}{" "}
          <button type="button" onClick={() => onChange(bands.filter((_, i) => i !== index))}>
            {t("tariff.remove_band")}
          </button>
        </li>
      ))}
      <li>
        <button
          type="button"
          onClick={() => onChange([...bands, { start_hour: 0, end_hour: 6, eur_kwh: fallback, weekdays: [], months: [] }])}
        >
          {t("tariff.add_band")}
        </button>
      </li>
    </ul>
  );
}

function ColorsEditor({ tariff, onChange }: { tariff: Tariff; onChange: (tariff: Tariff) => void }) {
  const { t } = useI18n();
  const setColor = (index: number, change: Partial<ColorPrices>) =>
    onChange({ ...tariff, colors: tariff.colors.map((c, i) => (i === index ? { ...c, ...change } : c)) });
  return (
    <>
      <p>
        <Entity label={t("tariff.color_entity")} value={tariff.color_entity} onChange={(color_entity) => onChange({ ...tariff, color_entity })} />
        <Hint text={t("tariff.color_entity_hint")} />
      </p>
      <Advanced
        modified={tariff.color_tomorrow_entity !== null || tariff.color_day_start_hour !== TARIFF_TEMPLATES.DayColorTariff.color_day_start_hour}
      >
      <p>
        <Entity
          label={t("tariff.color_tomorrow_entity")}
          value={tariff.color_tomorrow_entity}
          onChange={(color_tomorrow_entity) => onChange({ ...tariff, color_tomorrow_entity })}
        />
      </p>
      <p>
        <Hour
          label={t("tariff.color_day_start")}
          value={tariff.color_day_start_hour}
          from={0}
          to={23}
          onChange={(color_day_start_hour) => onChange({ ...tariff, color_day_start_hour })}
        />
      </p>
      </Advanced>
      <p>{t("tariff.colors_hint")}</p>
      {tariff.colors.map((color, index) => (
        <fieldset key={index} aria-label={t("tariff.color_named", { color: color.color })}>
          <label>
            {t("tariff.color")}{" "}
            <input value={color.color} onChange={(event) => setColor(index, { color: event.target.value })} />
          </label>{" "}
          <Price label={t("tariff.base_color")} value={color.base_eur_kwh} onChange={(base_eur_kwh) => setColor(index, { base_eur_kwh })} />{" "}
          <button type="button" onClick={() => onChange({ ...tariff, colors: tariff.colors.filter((_, i) => i !== index) })}>
            {t("tariff.remove_color")}
          </button>
          <BandsEditor
            bands={color.bands}
            fallback={color.base_eur_kwh}
            label={`${color.color} · `}
            onChange={(bands) => setColor(index, { bands })}
          />
        </fieldset>
      ))}
      <button
        type="button"
        onClick={() =>
          onChange({ ...tariff, colors: [...tariff.colors, { color: "", base_eur_kwh: tariff.base_eur_kwh, bands: [] }] })
        }
      >
        {t("tariff.add_color")}
      </button>
    </>
  );
}

type Proposal = "idle" | "loading" | "none" | "not_connected" | "failed";

function ProposeButton({ onChange }: { onChange: (tariff: Tariff) => void }) {
  const { t } = useI18n();
  const [state, setState] = useState<Proposal>("idle");
  const propose = async () => {
    setState("loading");
    try {
      const proposal = await getJson<Tariff | null>("api/configuration/tariff-proposal");
      if (proposal === null) {
        setState("none");
      } else {
        setState("idle");
        onChange(proposal);
      }
    } catch (error) {
      setState(error instanceof ApiError && error.status === 503 ? "not_connected" : "failed");
    }
  };
  return (
    <>
      <button type="button" onClick={() => void propose()} disabled={state === "loading"}>
        {t("tariff.propose")}
      </button>
      {state !== "idle" && state !== "loading" && <p role="status">{t(`tariff.proposal.${state}`)}</p>}
    </>
  );
}

export default function TariffEditor({ tariff, onChange }: { tariff: Tariff | null; onChange: (tariff: Tariff | null) => void }) {
  const { t } = useI18n();

  if (tariff === null) {
    return (
      <div>
        <p>{t("tariff.none", { price: DEFAULT_PRICE_EUR_KWH })}</p>
        <ProposeButton onChange={onChange} />{" "}
        {TARIFF_KINDS.map((kind) => (
          <button key={kind} type="button" onClick={() => onChange(TARIFF_TEMPLATES[kind])}>
            {t(`tariff.use.${kind}`)}
          </button>
        ))}
      </div>
    );
  }

  const baseLabel = {
    SingleTariff: "tariff.base_single",
    TimeOfUseTariff: "tariff.base_time_of_use",
    DayColorTariff: "tariff.base_unknown",
    DynamicTariff: "tariff.base_unknown",
  }[tariff.kind];

  // Unité des prix lus dans HA : visible pour le prix dynamique, avancée pour la revente seule.
  const unitSelect = (
    <label>
        {t("tariff.unit")}{" "}
        <select value={tariff.price_factor} onChange={(event) => onChange({ ...tariff, price_factor: Number(event.target.value) })}>
          {PRICE_UNITS.map(({ factor, unit }) => (
            <option key={factor} value={factor}>
              {unit}
            </option>
          ))}
        </select>
      </label>
  );

  return (
    <div>
      <label>
        {t("tariff.kind")}{" "}
        <select
          value={tariff.kind}
          onChange={(event) => {
            const kind = event.target.value as TariffKind;
            onChange({
              ...TARIFF_TEMPLATES[kind],
              export_eur_kwh: tariff.export_eur_kwh,
              export_entity: tariff.export_entity,
              subscription_eur_month: tariff.subscription_eur_month,
              contract_kva: tariff.contract_kva,
            });
          }}
        >
          {TARIFF_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`tariff.kinds.${kind}`)}
            </option>
          ))}
        </select>
      </label>
      <Hint text={t(`tariff.kind_hints.${tariff.kind}`)} />
      <p>
        <Price label={t(baseLabel)} value={tariff.base_eur_kwh} onChange={(base_eur_kwh) => onChange({ ...tariff, base_eur_kwh })} />
      </p>
      {tariff.kind === "TimeOfUseTariff" && (
        <BandsEditor bands={tariff.bands} fallback={tariff.base_eur_kwh} label="" onChange={(bands) => onChange({ ...tariff, bands })} />
      )}
      {tariff.kind === "DayColorTariff" && <ColorsEditor tariff={tariff} onChange={onChange} />}
      {tariff.kind === "DynamicTariff" && (
        <p>
          <Entity label={t("tariff.price_entity")} value={tariff.price_entity} onChange={(price_entity) => onChange({ ...tariff, price_entity })} />
          <Hint text={t("tariff.price_entity_hint")} />
        </p>
      )}
      {tariff.kind === "DynamicTariff" && (
        <p>{unitSelect}</p>
      )}
      <p>
        <Price
          label={t(tariff.export_entity ? "tariff.export_unknown" : "tariff.export")}
          value={tariff.export_eur_kwh}
          onChange={(export_eur_kwh) => onChange({ ...tariff, export_eur_kwh })}
        />
        <Hint text={t("tariff.export_hint")} />
      </p>
      <Advanced modified={tariff.export_entity !== null}>
        <p>
          <Entity label={t("tariff.export_entity")} value={tariff.export_entity} onChange={(export_entity) => onChange({ ...tariff, export_entity })} />
        </p>
        {tariff.kind !== "DynamicTariff" && tariff.export_entity !== null && <p>{unitSelect}</p>}
      </Advanced>
      <Contract tariff={tariff} onChange={onChange} />
      <ProposeButton onChange={onChange} />{" "}
      <button type="button" onClick={() => onChange(null)}>
        {t("tariff.reset")}
      </button>
    </div>
  );
}
