// « Mes demandes » (lot 4.5) : les équipements qu'on a demandé de faire tourner, sans date ou au
// plus tard tel jour, sans créer de liste de tâches dans Home Assistant. Le calcul place la
// demande comme une tâche « à la demande » de HA ; elle devient « faite » le lendemain du
// lancement constaté, ou à la main. Ici, la liste seulement : pour chaque demande, l'appareil,
// à droite où elle en est (et son heure de fin souhaitée), et dessous ses boutons, toujours
// visibles. Sous un jour de Planning
// (`day`), seulement les demandes de ce jour : celles que le calcul y place ou qui y ont été
// lancées (`planned_day`, donné par le serveur) ; sous Aujourd'hui (`today`), aussi celles qu'il
// n'a encore placées nulle part. Sans `day` (Semaine), toutes, avec leur jour prévu. Sous un
// jour à venir (`future` : Demain, J+2…, Semaine), rien ne peut avoir été lancé ni fait : seul
// « Annuler » reste. Une nouvelle demande passe par
// « Demander un appareil » (menu, ou `+` de la barre du haut) : la liste est relue quand une
// demande est déposée (`REQUESTS_EVENT`).

import { lazy, Suspense, useEffect, useState } from "react";

import { getJson, postJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import { cycleLabels } from "../plan/cycleLabel";
import { declareLaunched } from "../plan/declared";
import { hour } from "../plan/format";
import Panel from "../ui/Panel";
import type { RequestDevice } from "./RequestForm";
import { REQUESTS_EVENT } from "./pendingLatest";

// La feuille « Demander un appareil », chargée au premier « Modifier ».
const RequestSheet = lazy(() => import("./RequestSheet"));

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
  // Jour où la demande tourne (lancement constaté, sinon jour choisi par le calcul) ; aucun :
  // pas encore placée.
  planned_day?: string | null;
}

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; devices: RequestDevice[]; requests: UserRequest[] };

export default function RequestsSection({
  future = false,
  day: shownDay,
  today = false,
  computedAt = null,
  started = [],
}: {
  future?: boolean; // jour à venir ou semaine : ni « Fait » ni « C'est lancé »
  day?: string; // jour affiché (AAAA-MM-JJ) : ses demandes seulement ; aucun : toutes
  today?: boolean; // le jour affiché est aujourd'hui : les demandes pas encore placées aussi
  // Heure du calcul du plan affiché : une demande déposée après lui n'y est pas encore.
  computedAt?: string | null;
  // Cycles du jour déjà vus dans les mesures : leur demande est « lancée », même si le calcul
  // qui le note sur la demande n'a pas encore tourné (la tuile disait « lancé, en cours », la
  // demande « marqué comme lancé »).
  started?: string[];
}) {
  const { language, t } = useI18n();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [version, setVersion] = useState(0);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<UserRequest | null>(null); // demande ouverte par « Modifier »

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
  const everyOpen = requests.filter((r) => r.status === "open");
  const opened =
    shownDay === undefined
      ? everyOpen
      : everyOpen.filter(
          (r) => r.planned_day === shownDay || r.launched_on === shownDay || (today && r.planned_day == null),
        );
  // Demandes closes : sous un jour, celles qui y ont été lancées (hier : la lessive faite), à la
  // suite des demandes en cours et sans bouton ; l'historique entier sous Semaine seulement.
  const everyClosed = requests.filter((r) => r.status !== "open");
  const closedThatDay = shownDay === undefined ? [] : everyClosed.filter((r) => r.launched_on === shownDay);
  const closed = shownDay === undefined ? everyClosed : [];
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
  // Demandes en cours placées dans le plan du jour : le nom de leur cycle, numéroté dès que
  // l'équipement en a plusieurs — deux « Sèche-linge » sans numéro ne disaient pas lequel
  // marquer « Fait » (constaté le 28/11/2026).
  const labels = cycleLabels(
    load.requests.flatMap((request) => (request.status === "open" && request.cycle ? [request.cycle] : [])),
  );
  const openName = (request: UserRequest) => (request.cycle ? labels.get(request.cycle) : undefined) ?? name(request);

  // Où en est une demande en cours : lancée, déclarée lancée, pas encore calculée ou placée ; sinon rien,
  // sauf l'heure de fin souhaitée si elle en a une. Sous un jour, sa date ne se redit pas (« au
  // plus tard lundi » sous lundi n'apprenait rien, et passait pour une échéance qu'on n'avait
  // pas donnée) ; sous Semaine, le jour où elle tourne.
  const state = (request: UserRequest) => {
    const week = shownDay === undefined;
    if (request.launched_on) {
      return week ? `${t("plan.agenda.launched")} · ${day(request.launched_on)}` : t("plan.agenda.launched");
    }
    if (request.cycle && started.includes(request.cycle)) return t("plan.agenda.launched");
    if (request.declared) return t("requests.state_declared");
    // Déposée après le calcul du plan affiché : il ne la connaît pas encore (« La journée » ne
    // la montre pas) ; le prochain calcul, ou « Calculer », la placera.
    const pending = computedAt != null && new Date(request.created_at) > new Date(computedAt);
    const when = pending
      ? t("requests.not_computed")
      : request.planned_day == null
        ? t("requests.not_placed")
        : week
          ? t("requests.planned_on", { day: day(request.planned_day) })
          : null;
    const finish =
      request.finish_hour == null ? null : t("requests.state_finish", { hour: hour(request.finish_hour, language) });
    return [when, finish].filter(Boolean).join(" · ");
  };

  return (
    <Panel title={t("requests.title")} className="plan-requests">
      {failed && <p role="alert">{t("requests.failed")}</p>}
      {editing && (
        <Suspense fallback={null}>
          <RequestSheet
            editing={{ device: editing.device, latest: editing.latest, finish_hour: editing.finish_hour }}
            onClose={() => setEditing(null)}
          />
        </Suspense>
      )}
      {opened.length + closedThatDay.length === 0 ? (
        <p className="dim">{t(shownDay === undefined ? "requests.none" : "requests.none_day")}</p>
      ) : (
        <ul className="requests-list" aria-label={t("requests.open_list")}>
          {opened.map((request) => (
            <li key={request.id}>
              <span className="requests-name">{openName(request)}</span>
              <span className="requests-state">{state(request)}</span>
              <span className="requests-actions">
                  {!future && request.cycle && !request.launched_on && !request.declared && !started.includes(request.cycle) && (
                    <button type="button" onClick={() => void act(() => declareLaunched(request.cycle ?? ""))}>
                      {t("requests.mark_launched")}
                    </button>
                  )}
                  {!future && (
                    <button type="button" onClick={() => void act(() => postJson(`api/requests/${request.id}/done`, {}))}>
                      {t("requests.mark_done")}
                    </button>
                  )}
                  {/* Tant que le cycle n'est pas lancé : changer la date ou l'heure de fin, dans
                      la feuille de la demande déjà remplie (le formulaire n'est plus dans ce
                      panneau, et « Annuler » restait seul sous un jour à venir, 24/11/2026). */}
                  {!request.launched_on && !request.declared && !(request.cycle && started.includes(request.cycle)) && (
                    <button type="button" onClick={() => setEditing(request)}>
                      {t("requests.edit")}
                    </button>
                  )}
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
              </span>
            </li>
          ))}
          {closedThatDay.map((request) => (
            <li key={request.id}>
              <span className="requests-name">{name(request)}</span>
              <span className="requests-state">
                {t(request.status === "done" ? "requests.state_done" : "requests.state_cancelled")}
              </span>
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
