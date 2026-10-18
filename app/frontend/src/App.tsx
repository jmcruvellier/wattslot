import { lazy, Suspense, useEffect, useState } from "react";

import { reveal } from "./common/reveal";
import { returnedFromHomeAssistant } from "./connection/address";
import PlanScreen from "./plan/PlanScreen";
import StartScreen from "./start/StartScreen";
import { useI18n } from "./i18n/I18nProvider";
import MainMenu from "./nav/MainMenu";
import { useMenuCollapsed } from "./nav/menu";
import { DEFAULT_ROUTE, resolveTarget, routeHash, SUBPAGES, useRoute, type Route } from "./nav/routes";
import StatusPill from "./nav/StatusPill";
import { useStatusLevel } from "./nav/status";
import { type LatestRelease, UpdateContext, useUpdate, type UpdateState } from "./nav/updates";
import Icon from "./ui/Icon";
import { SettingList } from "./ui/SettingRow";

export interface HomeAssistantHealth {
  state: "not_configured" | "connecting" | "connected" | "error";
  version: string | null;
  error: string | null;
}

export interface Health {
  version: string;
  mode: "addon" | "standalone";
  connections: { home_assistant: HomeAssistantHealth };
}

type HealthState =
  | { status: "loading" }
  | { status: "ok"; health: Health }
  | { status: "error"; detail: string };

// Écrans chargés à la demande : seuls la mise en route et le plan du jour, ouverts au démarrage,
// restent dans le fichier principal (budget vérifié par scripts/check-size.mjs).
const AssistantScreen = lazy(() => import("./assistant/AssistantScreen"));
const ConnectionScreen = lazy(() => import("./connection/ConnectionScreen"));
const DiagnosticScreen = lazy(() => import("./diagnostic/DiagnosticScreen"));
const HomeScreen = lazy(() => import("./home/HomeScreen"));
import type { HomePage } from "./home/HomeScreen";
const LibraryScreen = lazy(() => import("./library/LibraryScreen"));
const SettingsScreen = lazy(() => import("./settings/SettingsScreen"));
// Démonstration des composants (lot 6b.1), hors du menu : adresse #/ui.
const UiGallery = lazy(() => import("./ui/UiGallery"));
// Feuille « Demander un appareil » (lot 6b.2), lue à la première ouverture.
const RequestSheet = lazy(() => import("./start/RequestSheet"));

// URL relative : l'application est servie sous un préfixe variable derrière l'ingress de HA.
const HEALTH_URL = "api/health";

// Cinq sections (lot 6b.2) ; l'accueil (mise en route puis plan du jour) s'ouvre par défaut, la
// connexion au retour de Home Assistant (lot 4.6).
const CONNECTION_ROUTE: Route = { section: "settings", sub: "connection" };

export default function App() {
  const { t } = useI18n();
  const [state, setState] = useState<HealthState>({ status: "loading" });
  // Retour de Home Assistant après « Se connecter avec Home Assistant » (lot 4.6).
  const [returned] = useState(() => returnedFromHomeAssistant());
  const [route, setRoute] = useRoute(returned ? CONNECTION_ROUTE : DEFAULT_ROUTE);
  const [collapsed, toggleMenu] = useMenuCollapsed();
  const [anchor, setAnchor] = useState<string | null>(null);
  const status = useStatusLevel();
  const [requesting, setRequesting] = useState(false);
  // Nouvelle version (lot 7.1) : vérifiée au chargement puis toutes les heures.
  const update = useUpdate(state.status === "ok" ? state.health.version : null);

  // Une étape de la mise en route ou un problème du diagnostic ouvre une page et, s'il y en a
  // une, une ancre : la section n'existe qu'une fois ses données lues, d'où quelques essais.
  const navigate = (target: string) => {
    const found = resolveTarget(target);
    if (!found) return;
    setRoute(found.route);
    setAnchor(found.anchor);
  };
  useEffect(() => {
    if (!anchor) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      // Déplie au besoin la section repliée qui contient l'ancre (lot 6b.5).
      if (reveal(anchor) || tries > 20) {
        window.clearInterval(timer);
        setAnchor(null);
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [anchor, route]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(HEALTH_URL, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setState({ status: "ok", health: (await response.json()) as Health });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", detail: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, []);

  const title =
    route.section === "ui" ? t("ui.title") : t(route.sub ? `nav.${route.sub}` : `nav.${route.section}`);
  useEffect(() => {
    document.title = `${title} · ${t("app.title")}`;
  }, [title, t]);

  return (
    <UpdateContext.Provider value={update}>
      <div className="app-shell" data-menu={collapsed ? "collapsed" : "open"}>
        <MainMenu
          route={route}
          collapsed={collapsed}
          onToggle={toggleMenu}
          top={<RequestButton onClick={() => setRequesting(true)} />}
          bottom={<StatusPill level={status} />}
        />
        <main>
          <header className="top-bar">
            {route.section !== "ui" && route.sub && (
              <a className="back-link" href={routeHash({ section: route.section, sub: null })}>
                <Icon name="chevron-left" size={18} />
                {t(`nav.${route.section}`)}
              </a>
            )}
            <div className="top-bar-row">
              <h1>{title}</h1>
              {/* Sur téléphone ; sur ordinateur, les mêmes sont dans le menu (styles.css). */}
              <div className="top-bar-actions">
                <StatusPill level={status} />
                <RequestButton compact onClick={() => setRequesting(true)} />
              </div>
            </div>
          </header>
          {requesting && (
            <Suspense fallback={null}>
              <RequestSheet onClose={() => setRequesting(false)} />
            </Suspense>
          )}

          <Suspense fallback={<p>{t("app.screen_loading")}</p>}>
            {route.section === "ui" && <UiGallery />}
            {route.section === "today" && <StartScreen onNavigate={navigate} />}
            {route.section === "planning" && <PlanScreen />}
            {route.section === "home" && route.sub !== "library" && (
              <HomeScreen
                page={(route.sub ?? "main") as HomePage}
                onNavigate={navigate}
                more={<MoreLinks section="home" />}
              />
            )}
            {route.sub === "library" && <LibraryScreen />}
            {route.section === "settings" &&
              (!route.sub || route.sub === "notifications" || route.sub === "calculation" || route.sub === "display") && (
                <SettingsScreen page={route.sub ?? "main"} />
              )}
            {route.section === "assistant" && <AssistantScreen />}
            {route.sub === "connection" && <ConnectionScreen returned={returned} />}
            {route.sub === "status" && (
              <>
                {/* Nouvelle version en tête de page, hors du détail technique replié (lot 7.1). */}
                {update.status === "available" && state.status === "ok" && (
                  <UpdateBanner latest={update.latest} mode={state.health.mode} />
                )}
                <DiagnosticScreen onNavigate={navigate}>
                  {state.status === "loading" && <p>{t("health.loading")}</p>}
                  {state.status === "error" && (
                    <p role="alert">{t("health.error", { status: state.detail })}</p>
                  )}
                  {state.status === "ok" && (
                    <dl>
                      <dt>{t("health.mode")}</dt>
                      <dd>{t(`mode.${state.health.mode}`)}</dd>
                      <dt>{t("health.home_assistant")}</dt>
                      <HomeAssistantStatus status={state.health.connections.home_assistant} />
                      <dt>{t("app.title")}</dt>
                      <dd>{t("health.version", { version: state.health.version })}</dd>
                      <UpdateNotice update={update} />
                      <dt>{t("health.support")}</dt>
                      <SupportLinks />
                    </dl>
                  )}
                </DiagnosticScreen>
              </>
            )}
          </Suspense>
        </main>
      </div>
    </UpdateContext.Provider>
  );
}

/** Ligne « nouvelle version » du détail technique d'État de l'application (lot 7.1) ; rien tant
 * que la vérification n'a pas répondu. */
function UpdateNotice({ update }: { update: UpdateState }) {
  const { t } = useI18n();
  if (update.status === "unknown") return null;
  if (update.status === "unavailable") return <dd className="dim">{t("updates.unavailable")}</dd>;
  if (update.status === "current") return <dd className="dim">{t("updates.current")}</dd>;
  return <dd>{t("updates.available", { version: update.latest.version })}</dd>;
}

/** Liens de soutien du détail technique d'État de l'application (lot 7.1), seul endroit de
 * l'interface où ils figurent : rien dans les écrans du quotidien. */
function SupportLinks() {
  return (
    <dd>
      <a href="https://github.com/sponsors/jmcruvellier" target="_blank" rel="noreferrer">
        GitHub Sponsors
      </a>
      {" · "}
      <a href="https://ko-fi.com/jmcruvellier" target="_blank" rel="noreferrer">
        Ko-fi
      </a>
    </dd>
  );
}

/** Encadré en tête d'État de l'application quand une version plus récente existe (lot 7.1). */
function UpdateBanner({ latest, mode }: { latest: LatestRelease; mode: Health["mode"] }) {
  const { t } = useI18n();
  return (
    <div className="card update-banner" role="status">
      <p>
        <strong>{t("updates.available", { version: latest.version })}</strong>{" "}
        <a href={latest.url} target="_blank" rel="noreferrer">
          {t("updates.notes")}
        </a>
      </p>
      <p>{t(mode === "addon" ? "updates.addon" : "updates.standalone")}</p>
      {mode === "standalone" && <code className="update-command">docker compose pull && docker compose up -d</code>}
    </div>
  );
}

// « Demander un appareil » : bouton du menu, ou icône seule dans la barre du haut du téléphone.
function RequestButton({ compact = false, onClick }: { compact?: boolean; onClick: () => void }) {
  const { t } = useI18n();
  if (compact) {
    return (
      <button type="button" className="ui-icon-button request-button-compact" aria-label={t("nav.request")} onClick={onClick}>
        <Icon name="plus" />
      </button>
    );
  }
  return (
    <button type="button" className="ui-button ui-button-primary request-button" title={t("nav.request")} onClick={onClick}>
      <Icon name="plus" size={18} />
      <span className="main-menu-label">{t("nav.request")}</span>
    </button>
  );
}

// « Pour aller plus loin » : sous-pages d'une section, en bas de sa page, sous un titre comme
// dans la liste des Réglages.
function MoreLinks({ section }: { section: keyof typeof SUBPAGES }) {
  const { t } = useI18n();
  return (
    <nav className="more-links" aria-label={t("nav.more")}>
      <h2 className="home-summary-heading">{t("nav.more")}</h2>
      <SettingList>
        {SUBPAGES[section].map((sub) => (
          <a key={sub} className="ui-setting-row ui-setting-row-open" href={routeHash({ section, sub })}>
            <span className="ui-row-label">{t(`nav.${sub}`)}</span>
            <Icon name="chevron-right" size={18} />
          </a>
        ))}
      </SettingList>
    </nav>
  );
}

function HomeAssistantStatus({ status }: { status: HomeAssistantHealth }) {
  const { t } = useI18n();
  return (
    <>
      <dd>{t(`connection.${status.state}`)}</dd>
      {status.version && <dd>{t("health.home_assistant_version", { version: status.version })}</dd>}
      {status.state === "error" && status.error && (
        <dd>{t("health.home_assistant_error", { error: status.error })}</dd>
      )}
    </>
  );
}
