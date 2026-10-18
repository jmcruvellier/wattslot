// « Mes demandes » (lot 4.5) : demander qu'un équipement tourne, sans date ou au plus tard tel
// jour, sans créer de liste de tâches dans Home Assistant. Le calcul place la demande comme une
// tâche « à la demande » de HA ; elle devient « faite » le lendemain du lancement constaté, ou à
// la main.

import { useEffect, useState } from "react";

import { getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import RequestForm, { type RequestDevice } from "./RequestForm";

export interface UserRequest {
  id: number;
  device: string;
  created_at: string;
  latest: string | null;
  status: "open" | "done" | "cancelled";
  launched_on: string | null;
  closed_at: string | null;
}


type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; devices: RequestDevice[]; requests: UserRequest[] };

export default function RequestsSection() {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [version, setVersion] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<RequestDevice[]>("api/requests/devices", controller.signal),
      getJson<UserRequest[]>("api/requests", controller.signal),
    ])
      .then(([devices, requests]) => setLoad({ status: "ready", devices, requests }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ status: "error" });
      });
    return () => controller.abort();
  }, [version]);

  if (load.status === "loading") return null;
  if (load.status === "error") return <p role="alert">{t("requests.error")}</p>;
  const { devices, requests } = load;
  if (devices.length === 0) return null; // aucun équipement qu'on lance : rien à demander
  const names = new Map(devices.map((d) => [d.key, d.name]));
  const opened = requests.filter((r) => r.status === "open");
  const closed = requests.filter((r) => r.status !== "open");
  const day = (iso: string) =>
    new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString(language, {
      weekday: "long",
      day: "numeric",
      month: "long",
    });

  const act = async (run: () => Promise<Response | unknown>) => {
    setFailed(false);
    try {
      await run();
    } catch {
      setFailed(true);
    }
    setVersion((count) => count + 1);
  };

  const describe = (request: UserRequest) => {
    const name = names.get(request.device) ?? request.device;
    if (request.status === "done") return t("requests.done_item", { device: name });
    if (request.status === "cancelled") return t("requests.cancelled_item", { device: name });
    if (request.launched_on) return t("requests.launched", { device: name });
    return request.latest
      ? t("requests.open_latest", { device: name, latest: day(request.latest) })
      : t("requests.open_asap", { device: name });
  };

  return (
    <section aria-labelledby="requests-title">
      <h2 id="requests-title">{t("requests.title")}</h2>
      <p>{t("requests.intro")}</p>
      <RequestForm devices={devices} onAsked={() => setVersion((count) => count + 1)} />
      {failed && <p role="alert">{t("requests.failed")}</p>}
      {opened.length === 0 ? (
        <p>{t("requests.none")}</p>
      ) : (
        <ul aria-label={t("requests.open_list")}>
          {opened.map((request) => (
            <li key={request.id}>
              {describe(request)}{" "}
              <button
                type="button"
                onClick={() => void act(() => postJson(`api/requests/${request.id}/done`, {}))}
              >
                {t("requests.mark_done")}
              </button>{" "}
              <button
                type="button"
                onClick={() =>
                  void act(async () => {
                    const response = await fetch(`api/requests/${request.id}`, { method: "DELETE" });
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                  })
                }
              >
                {t("requests.cancel")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {closed.length > 0 && (
        <details>
          <summary>{t("requests.recent")}</summary>
          <ul>
            {closed.map((request) => (
              <li key={request.id}>{describe(request)}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
