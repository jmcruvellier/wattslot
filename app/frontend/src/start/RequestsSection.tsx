// « Mes demandes » (lot 4.5) : les équipements qu'on a demandé de faire tourner, sans date ou au
// plus tard tel jour, sans créer de liste de tâches dans Home Assistant. Le calcul place la
// demande comme une tâche « à la demande » de HA ; elle devient « faite » le lendemain du
// lancement constaté, ou à la main. Ici, la liste seulement, une ligne par demande (l'appareil,
// et à droite son échéance) ; ses boutons se déplient au toucher. Une nouvelle demande passe par
// « Demander un appareil » (menu, ou `+` de la barre du haut) : la liste est relue quand une
// demande est déposée (`REQUESTS_EVENT`).

import { useEffect, useState } from "react";

import { getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { declareLaunched } from "../plan/declared";
import { hour } from "../plan/format";
import Icon from "../ui/Icon";
import Panel from "../ui/Panel";
import type { RequestDevice } from "./RequestForm";
import { REQUESTS_EVENT } from "./pendingLatest";

export interface UserRequest {
  id: number;
  device: string;
  created_at: string;
  latest: string | null;
  // Heure limite : cycle à terminer avant cette heure le jour où il tourne ; aucune : null.
  finish_hour?: number | null;
  status: "open" | "done" | "cancelled";
  launched_on: string | null;
  closed_at: string | null;
  // Demande placée dans le plan du jour : l'identité de son cycle (« Sèche-linge #2 »), et si
  // l'utilisateur l'a déjà déclaré lancé (« C'est lancé »).
  cycle?: string | null;
  declared?: boolean;
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

  // Demande déposée depuis la feuille « Demander un appareil » : la liste est relue.
  useEffect(() => {
    const reload = () => setVersion((count) => count + 1);
    window.addEventListener(REQUESTS_EVENT, reload);
    return () => window.removeEventListener(REQUESTS_EVENT, reload);
  }, []);

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

  const name = (request: UserRequest) => names.get(request.device) ?? request.device;

  // Où en est une demande en cours : lancée, déclarée lancée, ou son échéance.
  const state = (request: UserRequest) => {
    if (request.launched_on) return t("requests.state_launched");
    if (request.declared) return t("requests.state_declared");
    const text = request.latest
      ? t("requests.state_latest", { latest: day(request.latest) })
      : t("requests.state_asap");
    return request.finish_hour == null
      ? text
      : t("requests.with_finish", { request: text, hour: hour(request.finish_hour, language) });
  };

  return (
    <Panel title={t("requests.title")} className="plan-requests">
      {failed && <p role="alert">{t("requests.failed")}</p>}
      {opened.length === 0 ? (
        <p className="dim">{t("requests.none")}</p>
      ) : (
        <ul className="requests-list" aria-label={t("requests.open_list")}>
          {opened.map((request) => (
            <li key={request.id}>
              <details>
                <summary>
                  <span className="requests-name">
                    {name(request)} <Icon name="chevron-right" size={16} />
                  </span>
                  <span className="requests-state">{state(request)}</span>
                </summary>
                <div className="requests-actions">
                  {request.cycle && !request.launched_on && !request.declared && (
                    <button type="button" onClick={() => void act(() => declareLaunched(request.cycle ?? ""))}>
                      {t("requests.mark_launched")}
                    </button>
                  )}
                  <button type="button" onClick={() => void act(() => postJson(`api/requests/${request.id}/done`, {}))}>
                    {t("requests.mark_done")}
                  </button>
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
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
      {closed.length > 0 && (
        <details className="requests-recent">
          <summary>{t("requests.recent")}</summary>
          <ul>
            {closed.map((request) => (
              <li key={request.id}>
                {t(request.status === "done" ? "requests.done_item" : "requests.cancelled_item", { device: name(request) })}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}
