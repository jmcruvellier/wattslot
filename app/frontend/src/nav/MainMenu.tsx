// Menu principal (lot 6b.2) : un seul menu, en bas de l'écran sur téléphone, sur le côté sur
// ordinateur (styles.css). Replié, il ne garde que les icônes : chaque nom reste lu par les
// lecteurs d'écran et s'affiche en infobulle.

import type { ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import Icon from "../ui/Icon";
import { routeHash, SECTIONS, type Route } from "./routes";
import { useUpdateState } from "./updates";

interface MainMenuProps {
  route: Route;
  collapsed: boolean;
  onToggle: () => void;
  // Ajouts du lot 6b.2 (PR 2) : « Demander un appareil » en haut, pastille d'état en bas.
  top?: ReactNode;
  bottom?: ReactNode;
}

export default function MainMenu({ route, collapsed, onToggle, top, bottom }: MainMenuProps) {
  const { t } = useI18n();
  const update = useUpdateState();
  return (
    <nav className="main-menu" aria-label={t("nav.main")}>
      <div className="main-menu-head">
        <span className="main-menu-brand">
          {t("app.title")} <span className="beta-badge">{t("nav.beta")}</span>
        </span>
        <button
          type="button"
          className="ui-icon-button main-menu-toggle"
          aria-label={t(collapsed ? "nav.expand" : "nav.collapse")}
          title={t(collapsed ? "nav.expand" : "nav.collapse")}
          aria-expanded={!collapsed}
          onClick={onToggle}
        >
          <Icon name={collapsed ? "menu-expand" : "menu-collapse"} />
        </button>
      </div>
      {top}
      <ul>
        {SECTIONS.map((section) => (
          <li key={section}>
            <a
              href={routeHash({ section, sub: null })}
              aria-current={route.section === section ? "page" : undefined}
              title={collapsed ? t(`nav.${section}`) : undefined}
            >
              <Icon name={section} />
              <span className="main-menu-label">{t(`nav.${section}`)}</span>
              {/* Nouvelle version disponible (lot 7.1) : un point sur « Réglages ». */}
              {section === "settings" && update.status === "available" && (
                <>
                  <span className="update-dot" aria-hidden="true" />
                  <span className="visually-hidden">, {t("updates.menu")}</span>
                </>
              )}
            </a>
          </li>
        ))}
      </ul>
      {bottom}
    </nav>
  );
}
