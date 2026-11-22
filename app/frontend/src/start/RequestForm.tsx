// Formulaire d'une demande (lots 4.5 et 6b.2) : appareil et, si on veut, date « au plus tard »
// et heure limite « terminé avant » (issue 273 : lave-vaisselle demandé le soir, fini avant midi).
// Sert à « Mes demandes » et à la feuille « Demander un appareil ».

import { useState } from "react";

import { postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { hour } from "../plan/format";

export interface RequestDevice {
  key: string;
  name: string;
  // Faux : cycle pas encore connu du calcul (trop peu de cycles mesurés). Une demande resterait
  // ouverte sans jamais être placée : le formulaire le dit et ne la dépose pas.
  placeable?: boolean;
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
  // Heure limite de la demande en attente de chaque appareil (clé → heure, ou null : aucune) :
  // « Changer la date » la remplace par celle du formulaire, l'aide le dit.
  waitingFinish?: Record<string, number | null>;
  onAsked: () => void;
}

// Heures limites proposées : « avant 24 h » ne limiterait rien.
const FINISH_HOURS = Array.from({ length: 23 }, (_, index) => index + 1);

export default function RequestForm({
  devices,
  waiting = [],
  waitingLatest = {},
  waitingFinish = {},
  onAsked,
}: RequestFormProps) {
  const { language, t } = useI18n();
  const [device, setDevice] = useState("");
  const [latest, setLatest] = useState("");
  const [finish, setFinish] = useState(""); // heure limite choisie ; vide : aucune
  const [failed, setFailed] = useState(false);
  const selected = device || devices[0].key;
  const pending = waiting.includes(selected);
  const unknown = devices.find((d) => d.key === selected)?.placeable === false;
  const pendingLatest = waitingLatest[selected];
  const pendingFinish = waitingFinish[selected];
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
      // Sans heure limite, le champ n'est pas envoyé : le serveur n'en garde alors aucune.
      await postJson("api/requests", {
        device: selected,
        latest: latest || null,
        ...(finish ? { finish_hour: Number(finish) } : {}),
        ...(another ? { another: true } : {}),
      });
      setLatest("");
      setFinish("");
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
        <label>
          {t("requests.finish_before")}{" "}
          <select value={finish} onChange={(event) => setFinish(event.target.value)}>
            <option value="">{t("requests.finish_none")}</option>
            {FINISH_HOURS.map((h) => (
              <option key={h} value={h}>
                {hour(h, language)}
              </option>
            ))}
          </select>
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
        <small>
          {unknown ? t("requests.unknown_cycle") : pending ? waitingHint : t("requests.hint")}
          {!unknown && pending && pendingFinish != null && (
            <> {t("requests.waiting_finish", { hour: hour(pendingFinish, language) })}</>
          )}
          {!unknown && finish && <> {t("requests.finish_hint", { hour: hour(Number(finish), language) })}</>}
        </small>
      </p>
      {failed && <p role="alert">{t("requests.failed")}</p>}
    </>
  );
}
