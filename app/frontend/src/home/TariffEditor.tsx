// Tarif de la maison (lot 3.2) : prix unique, heures creuses et pleines, couleur du jour (Tempo)
// ou prix dynamique lu dans HA ; prix de revente fixe ou lu dans une entité. Chaque prix fixe peut
// suivre l'état d'une entité de HA (hass-tarif-edf, issue #54), le prix saisi servant de repli.
// Proposition d'après les prix déclarés dans le tableau Énergie de HA. Chaque plage peut être
// limitée à certains jours de la semaine (cases toujours visibles) et à certains mois (repliés
// sous « Toute l'année ») ; les jours fériés d'un pays peuvent compter comme un dimanche.

import { useEffect, useMemo, useState } from "react";

import { ApiError, getJson } from "../api";
import Advanced, { Hint } from "../common/Advanced";
import NumberInput from "../common/NumberInput";
import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import {
  DEFAULT_PRICE_EUR_KWH,
  PRICE_UNITS,
  TARIFF_KINDS,
  TARIFF_TEMPLATES,
  type ColorPrices,
  type Holidays,
  type PriceBand,
  type Tariff,
  type TariffKind,
} from "./configuration";

const HOURS = Array.from({ length: 25 }, (_, hour) => hour);
const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"] as const; // 0 lundi … 6 dimanche
const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];
const ALL_MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

// Cases cochées d'une liste où « vide » veut dire « toutes » ; la dernière case ne se décoche pas.
function toggled(chosen: number[], all: number[], value: number, on: boolean): number[] {
  const current = chosen.length === 0 ? all : chosen;
  const next = on ? [...current, value].sort((a, b) => a - b) : current.filter((v) => v !== value);
  return next.length === all.length ? [] : next;
}

// Jours de la semaine et mois d'une plage (vides : tous).
function BandDays({ band, onChange }: { band: PriceBand; onChange: (change: Partial<PriceBand>) => void }) {
  const { t, language } = useI18n();
  const days = band.weekdays.length === 0 ? ALL_DAYS : band.weekdays;
  const months = band.months.length === 0 ? ALL_MONTHS : band.months;
  const monthName = (month: number) => new Date(2026, month - 1, 1).toLocaleDateString(language, { month: "short" });
  return (
    <>
      <div className="band-days" role="group" aria-label={t("tariff.days")}>
        {t("tariff.days")}{" "}
        {WEEKDAYS.map((code, day) => (
          <label key={code} className="settings-inline">
            <input
              type="checkbox"
              checked={days.includes(day)}
              disabled={days.length === 1 && days.includes(day)}
              onChange={(event) => onChange({ weekdays: toggled(band.weekdays, ALL_DAYS, day, event.target.checked) })}
            />{" "}
            {t(`cycle.weekdays.${code}`)}{" "}
          </label>
        ))}
      </div>
      <details>
        <summary>
          {band.months.length === 0 ? t("tariff.all_year") : t("tariff.some_months", { months: band.months.map(monthName).join(", ") })}
        </summary>
        <div className="band-days" role="group" aria-label={t("tariff.months")}>
          {ALL_MONTHS.map((month) => (
            <label key={month} className="settings-inline">
              <input
                type="checkbox"
                checked={months.includes(month)}
                disabled={months.length === 1 && months.includes(month)}
                onChange={(event) => onChange({ months: toggled(band.months, ALL_MONTHS, month, event.target.checked) })}
              />{" "}
              {monthName(month)}{" "}
            </label>
          ))}
        </div>
      </details>
    </>
  );
}

interface HolidayChoices {
  default_country: string | null; // pays de Home Assistant
  country: string | null;
  countries: string[];
  subdivisions: { code: string; name: string }[];
}

const holidayUrl = (country: string | null) =>
  `api/configuration/holidays${country ? `?country=${encodeURIComponent(country)}` : ""}`;

// Jours fériés comptés comme un dimanche : pays (celui de HA par défaut) et région.
function HolidaysSetting({ tariff, onChange }: { tariff: Tariff; onChange: (tariff: Tariff) => void }) {
  const { t, language } = useI18n();
  const rule = tariff.holidays ?? null;
  const [choices, setChoices] = useState<HolidayChoices | null>(null);
  const [failed, setFailed] = useState(false);
  const enabled = rule !== null;
  const country = rule?.country || null;
  const names = useMemo(() => {
    try {
      return new Intl.DisplayNames([language], { type: "region" });
    } catch {
      return null;
    }
  }, [language]);
  const countryName = (code: string) => {
    try {
      return names?.of(code) ?? code;
    } catch {
      return code;
    }
  };

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    getJson<HolidayChoices>(holidayUrl(country))
      .then((found) => {
        if (!cancelled) setChoices(found);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, country]);

  const setRule = (holidays: Holidays | null) => onChange({ ...tariff, holidays });
  const countries = useMemo(
    () => [...(choices?.countries ?? [])].sort((a, b) => countryName(a).localeCompare(countryName(b), language)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- countryName ne dépend que de names
    [choices, names, language],
  );

  return (
    <p>
      <label>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => {
            if (!event.target.checked) {
              setRule(null);
              return;
            }
            setRule({ country: "", subdivision: null });
            getJson<HolidayChoices>(holidayUrl(null))
              .then((found) => {
                setChoices(found);
                onChange({ ...tariff, holidays: { country: found.default_country ?? "", subdivision: null } });
              })
              .catch(() => setFailed(true));
          }}
        />{" "}
        {t("tariff.holidays")}
      </label>
      <Hint text={t("tariff.holidays_hint")} />
      {rule !== null && (
        <>
          <br />
          <label>
            {t("tariff.holiday_country")}{" "}
            <select value={rule.country} onChange={(event) => setRule({ country: event.target.value, subdivision: null })}>
              {rule.country === "" && <option value="">{t("tariff.choose_country")}</option>}
              {rule.country !== "" && !countries.includes(rule.country) && (
                <option value={rule.country}>{countryName(rule.country)}</option>
              )}
              {countries.map((code) => (
                <option key={code} value={code}>
                  {countryName(code)}
                </option>
              ))}
            </select>
          </label>
          {choices !== null && choices.country === rule.country && choices.subdivisions.length > 0 && (
            <>
              {" "}
              <label>
                {t("tariff.holiday_region")}{" "}
                <select
                  value={rule.subdivision ?? ""}
                  onChange={(event) => setRule({ ...rule, subdivision: event.target.value === "" ? null : event.target.value })}
                >
                  <option value="">{t("tariff.whole_country")}</option>
                  {choices.subdivisions.map(({ code, name }) => (
                    <option key={code} value={code}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          {failed && <small role="status"> {t("tariff.holidays_failed")}</small>}
        </>
      )}
    </p>
  );
}

// Contrat (lot 7.3) : abonnement mensuel et puissance souscrite, quel que soit le tarif.
function Contract({ tariff, onChange }: { tariff: Tariff; onChange: (tariff: Tariff) => void }) {
  const { t } = useI18n();
  const { symbol } = useCurrency();
  return (
    <>
      <p>
        <label>
          {t("tariff.subscription")}{" "}
          <NumberInput
            min={0}
            step={0.01}
            value={tariff.subscription_eur_month}
            onChange={(subscription_eur_month) => onChange({ ...tariff, subscription_eur_month })}
          />{" "}
          {t("tariff.per_month", { symbol })}
        </label>
        <Hint text={t("tariff.subscription_hint")} />
      </p>
      <p>
        <label>
          {t("tariff.contract_kva")}{" "}
          <NumberInput
            nullable
            min={0.1}
            step={0.1}
            value={tariff.contract_kva}
            onChange={(contract_kva) => onChange({ ...tariff, contract_kva })}
          />{" "}
          kVA
        </label>
        <Hint text={t("tariff.contract_kva_hint")} />
      </p>
    </>
  );
}

// Prix saisi ; avec ``onEntity``, il peut suivre l'état d'une entité de HA (repli : le prix saisi).
function Price({ label, value, onChange, entity, onEntity }: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  entity?: string | null;
  onEntity?: (entity: string | null) => void;
}) {
  const { t } = useI18n();
  const { symbol } = useCurrency();
  const [reading, setReading] = useState(Boolean(entity));
  const linked = onEntity !== undefined && (reading || Boolean(entity));
  return (
    <>
      <label>
        {label}
        {linked && ` ${t("tariff.if_unavailable")}`}{" "}
        <NumberInput min={0} step={0.01} value={value} onChange={onChange} />{" "}
        {symbol}/kWh
      </label>
      {onEntity && !linked && (
        <>
          {" "}
          <button type="button" className="link" onClick={() => setReading(true)}>
            {t("tariff.read")}
          </button>
        </>
      )}
      {onEntity && linked && (
        <>
          {" "}
          <label>
            {t("tariff.read_from")}{" "}
            <input
              placeholder="sensor.…"
              value={entity ?? ""}
              onChange={(event) => onEntity(event.target.value.trim() === "" ? null : event.target.value.trim())}
            />
          </label>{" "}
          <button
            type="button"
            className="link"
            onClick={() => {
              setReading(false);
              onEntity(null);
            }}
          >
            {t("tariff.stop_reading")}
          </button>
        </>
      )}
    </>
  );
}

// Le tarif lit-il des prix fixes dans HA ? (l'unité des entités s'affiche alors)
function readsFixedPrices(tariff: Tariff): boolean {
  const owners = [tariff, ...tariff.colors];
  return owners.some((owner) => Boolean(owner.base_eur_kwh_entity) || owner.bands.some((band) => Boolean(band.eur_kwh_entity)));
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

function Minute({ label, value, disabled = false, onChange }: {
  label: string; // libellé accessible, invisible : la minute suit l'heure, « 10 h 30 »
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <select aria-label={label} disabled={disabled} value={value} onChange={(event) => onChange(Number(event.target.value))}>
      {Array.from({ length: 60 }, (_, minute) => (
        <option key={minute} value={minute}>{String(minute).padStart(2, "0")}</option>
      ))}
    </select>
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
          <Minute label={t("tariff.start_minute")} value={band.start_minute ?? 0} onChange={(start_minute) => setBand(index, { start_minute })} />{" "}
          <Hour label={t("tariff.to")} value={band.end_hour} from={1} to={24} onChange={(end_hour) => setBand(index, { end_hour, end_minute: end_hour === 24 ? 0 : (band.end_minute ?? 0) })} />{" "}
          <Minute label={t("tariff.end_minute")} value={band.end_hour === 24 ? 0 : (band.end_minute ?? 0)} disabled={band.end_hour === 24} onChange={(end_minute) => setBand(index, { end_minute })} />{" "}
          <Price
            label={t("tariff.price")}
            value={band.eur_kwh}
            onChange={(eur_kwh) => setBand(index, { eur_kwh })}
            entity={band.eur_kwh_entity}
            onEntity={(eur_kwh_entity) => setBand(index, { eur_kwh_entity })}
          />{" "}
          <button type="button" onClick={() => onChange(bands.filter((_, i) => i !== index))}>
            {t("tariff.remove_band")}
          </button>
          <BandDays band={band} onChange={(change) => setBand(index, change)} />
        </li>
      ))}
      <li>
        <button
          type="button"
          onClick={() => onChange([...bands, { start_hour: 0, start_minute: 0, end_hour: 6, end_minute: 0, eur_kwh: fallback, weekdays: [], months: [] }])}
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
          <Price
            label={t("tariff.base_color")}
            value={color.base_eur_kwh}
            onChange={(base_eur_kwh) => setColor(index, { base_eur_kwh })}
            entity={color.base_eur_kwh_entity}
            onEntity={(base_eur_kwh_entity) => setColor(index, { base_eur_kwh_entity })}
          />{" "}
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
  const { perKwh, symbol } = useCurrency();

  if (tariff === null) {
    return (
      <div>
        <p>{t("tariff.none", { price: perKwh(DEFAULT_PRICE_EUR_KWH) })}</p>
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

  // Unité des prix lus dans HA : visible pour le prix dynamique et les prix fixes lus dans HA,
  // avancée pour la revente seule.
  const unitSelect = (
    <label>
        {t("tariff.unit")}{" "}
        <select value={tariff.price_factor} onChange={(event) => onChange({ ...tariff, price_factor: Number(event.target.value) })}>
          {PRICE_UNITS.map(({ factor, unit }) => (
            <option key={factor} value={factor}>
              {t(`tariff.units.${unit}`, { symbol })}
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
              holidays: tariff.holidays,
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
        <Price
          label={t(baseLabel)}
          value={tariff.base_eur_kwh}
          onChange={(base_eur_kwh) => onChange({ ...tariff, base_eur_kwh })}
          entity={tariff.base_eur_kwh_entity}
          onEntity={(base_eur_kwh_entity) => onChange({ ...tariff, base_eur_kwh_entity })}
        />
      </p>
      {tariff.kind === "TimeOfUseTariff" && (
        <BandsEditor bands={tariff.bands} fallback={tariff.base_eur_kwh} label="" onChange={(bands) => onChange({ ...tariff, bands })} />
      )}
      {tariff.kind === "DayColorTariff" && <ColorsEditor tariff={tariff} onChange={onChange} />}
      {(tariff.kind === "TimeOfUseTariff" || tariff.kind === "DayColorTariff") && (
        <HolidaysSetting tariff={tariff} onChange={onChange} />
      )}
      {tariff.kind === "DynamicTariff" && (
        <p>
          <Entity label={t("tariff.price_entity")} value={tariff.price_entity} onChange={(price_entity) => onChange({ ...tariff, price_entity })} />
          <Hint text={t("tariff.price_entity_hint")} />
        </p>
      )}
      {(tariff.kind === "DynamicTariff" || readsFixedPrices(tariff)) && (
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
        {tariff.kind !== "DynamicTariff" && !readsFixedPrices(tariff) && tariff.export_entity !== null && <p>{unitSelect}</p>}
      </Advanced>
      <Contract tariff={tariff} onChange={onChange} />
      <ProposeButton onChange={onChange} />{" "}
      <button type="button" onClick={() => onChange(null)}>
        {t("tariff.reset")}
      </button>
    </div>
  );
}
