// Feuille « Mon raccordement » de « L'essentiel » : maison en monophasé ou en triphasé, et, en
// triphasé, ce que compte le compteur. Enregistrée avec la maison (/api/home) : ses appareils
// repartent tels qu'ils sont enregistrés. La phase de chaque appareil se règle dans sa fiche.

import { useState } from "react";

import { putJson } from "../api";
import { Hint } from "../common/Advanced";
import { useI18n } from "../i18n/I18nProvider";
import Button from "../ui/Button";
import Sheet from "../ui/Sheet";
import type { HomeData } from "./HomeSummary";
import type { HomeModel, Supply } from "./types";

const SUPPLIES: Supply[] = ["SinglePhaseSupply", "ThreePhaseSupply"];

export default function SupplySheet({
  data,
  onClose,
  onSaved,
}: {
  data: HomeData;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [supply, setSupply] = useState<Supply>(data.supply ?? "SinglePhaseSupply");
  const [sums, setSums] = useState(data.meterSumsPhases ?? true);
  const [status, setStatus] = useState<"idle" | "saving" | "failed">("idle");

  const onSave = async () => {
    setStatus("saving");
    const model: HomeModel = { devices: data.devices, supply, meter_sums_phases: sums };
    try {
      await putJson("api/home", model);
      onSaved();
    } catch {
      setStatus("failed");
    }
  };

  return (
    <Sheet open wide title={t("supply.title")} onClose={onClose}>
      <div className="expert-form">
        <label>
          {t("supply.kind")}{" "}
          <select
            value={supply}
            onChange={(event) => {
              setStatus("idle");
              setSupply(event.target.value as Supply);
            }}
          >
            {SUPPLIES.map((kind) => (
              <option key={kind} value={kind}>
                {t(`supply.kinds.${kind}`)}
              </option>
            ))}
          </select>
        </label>
        <Hint text={t("supply.kind_hint")} />
        {supply === "ThreePhaseSupply" && (
          <>
            <p>
              <label>
                <input
                  type="checkbox"
                  checked={sums}
                  onChange={(event) => {
                    setStatus("idle");
                    setSums(event.target.checked);
                  }}
                />{" "}
                {t("supply.meter_sums")}
              </label>
              <Hint text={t("supply.meter_sums_hint")} />
            </p>
            <p>{t("supply.phases_hint")}</p>
          </>
        )}
      </div>
      <div className="home-sheet-actions">
        {status === "failed" && <p role="alert">{t("home.save_failed")}</p>}
        <Button variant="primary" onClick={() => void onSave()} disabled={status === "saving"}>
          {t("configuration.save")}
        </Button>
      </div>
    </Sheet>
  );
}
