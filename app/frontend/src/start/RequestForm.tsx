// Formulaire d'une demande (lots 4.5 et 6b.2) : appareil et, si on veut, date « au plus tard ».
// Sert à « Mes demandes » et à la feuille « Demander un appareil ».

import { useState } from "react";

import { postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";

export interface RequestDevice {
  key: string;
  name: string;
}

interface RequestFormProps {
  devices: RequestDevice[];
  // Appareils (clés) qui ont déjà une demande en attente, pas encore lancée : le formulaire
  // propose alors de changer sa date ou d'ajouter un cycle (deux lessives le même jour).
  waiting?: string[];
  onAsked: () => void;
}

export default function RequestForm({ devices, waiting = [], onAsked }: RequestFormProps) {
  const { t } = useI18n();
  const [device, setDevice] = useState("");
  const [latest, setLatest] = useState("");
  const [failed, setFailed] = useState(false);
  const selected = device || devices[0].key;
  const pending = waiting.includes(selected);

  const ask = async (another = false) => {
    setFailed(false);
    try {
      // « another » : un cycle de plus, au lieu de changer la date de la demande en attente.
      await postJson("api/requests", { device: selected, latest: latest || null, ...(another ? { another: true } : {}) });
      setLatest("");
      onAsked();
    } catch {
      setFailed(true);
    }
  };

  return (
    <>
      <p className="request-form">
        <label>
          {t("requests.device")}{" "}
          <select value={selected} onChange={(event) => setDevice(event.target.value)}>
            {devices.map((d) => (
              <option key={d.key} value={d.key}>
                {d.name}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          {t("requests.latest")}{" "}
          <input type="date" value={latest} onChange={(event) => setLatest(event.target.value)} />
        </label>{" "}
        {pending ? (
          <>
            <button type="button" onClick={() => void ask()}>
              {t("requests.change_date")}
            </button>{" "}
            <button type="button" onClick={() => void ask(true)}>
              {t("requests.add_cycle")}
            </button>
          </>
        ) : (
          <button type="button" onClick={() => void ask()}>
            {t("requests.ask")}
          </button>
        )}
        <br />
        <small>{pending ? t("requests.waiting_hint") : t("requests.hint")}</small>
      </p>
      {failed && <p role="alert">{t("requests.failed")}</p>}
    </>
  );
}
