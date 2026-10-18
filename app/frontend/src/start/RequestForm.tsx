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
  onAsked: () => void;
}

export default function RequestForm({ devices, onAsked }: RequestFormProps) {
  const { t } = useI18n();
  const [device, setDevice] = useState("");
  const [latest, setLatest] = useState("");
  const [failed, setFailed] = useState(false);

  const ask = async () => {
    setFailed(false);
    try {
      await postJson("api/requests", { device: device || devices[0].key, latest: latest || null });
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
          <select value={device || devices[0].key} onChange={(event) => setDevice(event.target.value)}>
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
        <button type="button" onClick={() => void ask()}>
          {t("requests.ask")}
        </button>
        <br />
        <small>{t("requests.hint")}</small>
      </p>
      {failed && <p role="alert">{t("requests.failed")}</p>}
    </>
  );
}
