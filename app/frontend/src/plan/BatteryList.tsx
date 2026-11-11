// Chaque batterie de la maison : son état de charge au dernier relevé, son contenu et ce qu'elle
// fait en ce moment (puissance moyenne du dernier quart d'heure). Affiché dès qu'il y en a
// plusieurs : la carte Batterie d'Aujourd'hui, et la carte « Batteries » de Planning.

import { useI18n } from "../i18n/I18nProvider";
import Icon from "../ui/Icon";
import { kwh, percent } from "./format";
import type { BatteryNow, DayView } from "./types";

// Puissance lisible : watts sous le kilowatt, kilowatts au-delà.
function power(watts: number): string {
  const value = Math.round(Math.abs(watts));
  return value < 1000 ? `${kwh(value, 0)} W` : `${kwh(value / 1000, 1)} kW`;
}

export function BatteryList({ batteries }: { batteries: BatteryNow[] }) {
  const { t } = useI18n();
  const phase = (battery: BatteryNow) => {
    if (!battery.phase) return null;
    if (battery.phase === "ThreePhases") return t("batteries.three_phase");
    return t("batteries.phase", { number: battery.phase.slice(-1) });
  };
  const doing = (battery: BatteryNow) => {
    if (battery.power_w == null) return "—";
    if (Math.abs(battery.power_w) < 10) return t("batteries.idle");
    return t(battery.power_w > 0 ? "today.now.charging" : "today.now.discharging", { kw: power(battery.power_w) });
  };

  return (
    <table className="phases-table battery-table">
      <thead>
        <tr>
          <td />
          <th scope="col">{t("batteries.level")}</th>
          <th scope="col">{t("batteries.stored")}</th>
          <th scope="col">{t("batteries.doing")}</th>
        </tr>
      </thead>
      <tbody>
        {batteries.map((battery) => (
          <tr key={battery.key}>
            <th scope="row">
              {battery.name}
              {phase(battery) && <small className="dim">{phase(battery)}</small>}
            </th>
            <td>{battery.soc_percent == null ? "—" : `${percent(battery.soc_percent)} %`}</td>
            <td>{battery.stored_kwh == null ? "—" : `${kwh(battery.stored_kwh, 1)} kWh`}</td>
            <td>{doing(battery)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Carte « Batteries » de Planning (aujourd'hui) : absente avec une seule batterie.
export default function BatteriesCard({ view }: { view: DayView }) {
  const { t } = useI18n();
  const batteries = view.now?.batteries ?? [];
  if (batteries.length < 2) return null;
  return (
    <article className="card" aria-label={t("batteries.title")}>
      <h3>
        <Icon name="battery" size={20} /> {t("batteries.title")}
      </h3>
      <p className="dim">{t("batteries.note")}</p>
      <BatteryList batteries={batteries} />
    </article>
  );
}
