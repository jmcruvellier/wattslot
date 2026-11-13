// Feuille « Demander un appareil » (lot 6b.2) : toujours à portée, depuis le menu sur ordinateur
// et la barre du haut sur téléphone. Montée à l'ouverture, démontée à la fermeture : les appareils
// sont lus à chaque ouverture ; après l'envoi, la feuille confirme que le prochain calcul placera
// la demande.

import { useEffect, useState } from "react";

import { getJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import Button from "../ui/Button";
import Sheet from "../ui/Sheet";
import RequestForm, { type RequestDevice } from "./RequestForm";

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; devices: RequestDevice[]; waiting: string[] }
  | { status: "asked" };

export default function RequestSheet({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    // Les demandes en attente aussi : pour un appareil déjà demandé, le formulaire propose de
    // changer la date ou d'ajouter un cycle. Si elles ne se lisent pas, la feuille s'ouvre
    // quand même, avec le seul bouton « Demander ».
    type Asked = { device: string; status: string; launched_on: string | null };
    Promise.all([
      getJson<RequestDevice[]>("api/requests/devices", controller.signal),
      getJson<Asked[]>("api/requests", controller.signal).catch((): Asked[] => []),
    ])
      .then(([devices, requests]) =>
        setLoad({
          status: "ready",
          devices,
          waiting: requests.filter((r) => r.status === "open" && !r.launched_on).map((r) => r.device),
        }),
      )
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, []);

  return (
    <Sheet open title={t("nav.request")} onClose={onClose}>
      {load.status === "loading" && <p>{t("requests.loading")}</p>}
      {load.status === "error" && <p role="alert">{t("requests.error")}</p>}
      {load.status === "ready" &&
        (load.devices.length === 0 ? (
          <p>{t("requests.no_device")}</p>
        ) : (
          <>
            <p>{t("requests.intro")}</p>
            <RequestForm devices={load.devices} waiting={load.waiting} onAsked={() => setLoad({ status: "asked" })} />
          </>
        ))}
      {load.status === "asked" && (
        <>
          <p role="status">{t("requests.sheet_done")}</p>
          <Button variant="primary" onClick={onClose}>
            {t("requests.sheet_close")}
          </Button>
        </>
      )}
    </Sheet>
  );
}
