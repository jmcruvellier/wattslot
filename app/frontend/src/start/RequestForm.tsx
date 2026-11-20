// Formulaire d'une demande (lots 4.5 et 6b.2) : appareil et, si on veut, date « au plus tard ».
// Sert à « Mes demandes » et à la feuille « Demander un appareil ».

import { useState } from "react";

import { postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";

export interface RequestDevice {
  key: string;
  name: string;
  // Faux : cycle pas encore connu du calcul (trop peu de cycles mesurés). Une demande resterait
  // ouverte sans jamais être placée : le formulaire le dit et ne la dépose pas.
  placeable?: boolean;
}

/** Date de la demande en attente (pas encore lancée) de chaque appareil : celle que
 * « Changer la date » modifie, la plus récente. La liste du serveur donne les plus récentes
 * d'abord. */
export function pendingLatest(
  requests: { device: string; status: string; launched_on: string | null; latest: string | null }[],
): Record<string, string | null> {
  const found: Record<string, string | null> = {};
  for (const request of requests) {
    if (request.status === "open" && !request.launched_on && !(request.device in found)) {
      found[request.device] = request.latest;
    }
  }
  return found;
}

interface RequestFormProps {
  devices: RequestDevice[];
  // Appareils (clés) qui ont déjà une demande en attente, pas encore lancée : le formulaire
  // propose alors de changer sa date ou d'ajouter un cycle (deux lessives le même jour).
  waiting?: string[];
  // Date « au plus tard » de la demande en attente de chaque appareil (clé → date, ou null :
  // dès que possible) : l'aide la dit. Sans elle, « déjà une demande en attente » ne disait pas
  // laquelle, et une demande à la date passée passait pour une erreur (constaté le 19/11/2026).
  waitingLatest?: Record<string, string | null>;
  onAsked: () => void;
}

export default function RequestForm({ devices, waiting = [], waitingLatest = {}, onAsked }: RequestFormProps) {
  const { language, t } = useI18n();
  const [device, setDevice] = useState("");
  const [latest, setLatest] = useState("");
  const [failed, setFailed] = useState(false);
  const selected = device || devices[0].key;
  const pending = waiting.includes(selected);
  const unknown = devices.find((d) => d.key === selected)?.placeable === false;
  const pendingLatest = waitingLatest[selected];
  const waitingHint =
    pendingLatest === undefined
      ? t("requests.waiting_hint")
      : pendingLatest === null
        ? t("requests.waiting_hint_asap")
        : t("requests.waiting_hint_latest", {
            latest: new Date(`${pendingLatest.slice(0, 10)}T12:00:00`).toLocaleDateString(language, {
              weekday: "long",
              day: "numeric",
              month: "long",
            }),
          });

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
            <button type="button" disabled={unknown} onClick={() => void ask()}>
              {t("requests.change_date")}
            </button>{" "}
            <button type="button" disabled={unknown} onClick={() => void ask(true)}>
              {t("requests.add_cycle")}
            </button>
          </>
        ) : (
          <button type="button" disabled={unknown} onClick={() => void ask()}>
            {t("requests.ask")}
          </button>
        )}
        <br />
        <small>{unknown ? t("requests.unknown_cycle") : pending ? waitingHint : t("requests.hint")}</small>
      </p>
      {failed && <p role="alert">{t("requests.failed")}</p>}
    </>
  );
}
