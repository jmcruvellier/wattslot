// Cartes de la bêta publique (0.9.1), en bas des Réglages : « Donner mon avis » (modèle d'issue
// « Beta feedback » du dépôt) et « Soutenir WattSlot » (GitHub Sponsors, Ko-fi). Logos : Simple
// Icons (CC0), dans les couleurs des deux plateformes (styles.css).

import { useI18n } from "../i18n/I18nProvider";

export const FEEDBACK_URL = "https://github.com/jmcruvellier/wattslot/issues/new?template=beta_feedback.yml";
export const SPONSORS_URL = "https://github.com/sponsors/jmcruvellier";
export const KOFI_URL = "https://ko-fi.com/jmcruvellier";

const SPONSORS_PATH =
  "M17.625 1.499c-2.32 0-4.354 1.203-5.625 3.03-1.271-1.827-3.305-3.03-5.625-3.03C3.129 1.499 0 4.253 0 8.249c0 4.275 3.068 7.847 5.828 10.227a33.14 33.14 0 0 0 5.616 3.876l.028.017.008.003-.001.003c.163.085.342.126.521.125.179.001.358-.041.521-.125l-.001-.003.008-.003.028-.017a33.14 33.14 0 0 0 5.616-3.876C20.932 16.096 24 12.524 24 8.249c0-3.996-3.129-6.75-6.375-6.75zm-.919 15.275a30.766 30.766 0 0 1-4.703 3.316l-.004-.002-.004.002a30.955 30.955 0 0 1-4.703-3.316c-2.677-2.307-5.047-5.298-5.047-8.523 0-2.754 2.121-4.5 4.125-4.5 2.06 0 3.914 1.479 4.544 3.684.143.495.596.797 1.086.796.49.001.943-.302 1.085-.796.63-2.205 2.484-3.684 4.544-3.684 2.004 0 4.125 1.746 4.125 4.5 0 3.225-2.37 6.216-5.048 8.523z";
const KOFI_PATH =
  "M23.881 8.948c-.773-4.085-4.859-4.593-4.859-4.593H.723c-.604 0-.679.798-.679.798s-.082 7.324-.022 11.822c.164 2.424 2.586 2.672 2.586 2.672s8.267-.023 11.966-.049c2.438-.426 2.683-2.566 2.658-3.734 4.352.24 7.422-2.831 6.649-6.916zm-11.062 3.511c-1.246 1.453-4.011 3.976-4.011 3.976s-.121.119-.31.023c-.076-.057-.108-.09-.108-.09-.443-.441-3.368-3.049-4.034-3.954-.709-.965-1.041-2.7-.091-3.71.951-1.01 3.005-1.086 4.363.407 0 0 1.565-1.782 3.468-.963 1.904.82 1.832 3.011.723 4.311zm6.173.478c-.928.116-1.682.028-1.682.028V7.284h1.77s1.971.551 1.971 2.638c0 1.913-.985 2.667-2.059 3.015z";

function Logo({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
      <path d={path} fill="currentColor" />
    </svg>
  );
}

/** Liens de soutien, avec les logos : Réglages et État de l'application. */
export function SupportLinks() {
  return (
    <span className="support-links">
      <a className="support-link support-link-sponsors" href={SPONSORS_URL} target="_blank" rel="noreferrer">
        <Logo path={SPONSORS_PATH} /> GitHub Sponsors
      </a>
      <a className="support-link support-link-kofi" href={KOFI_URL} target="_blank" rel="noreferrer">
        <Logo path={KOFI_PATH} /> Ko-fi
      </a>
    </span>
  );
}

export default function BetaCards() {
  const { t } = useI18n();
  return (
    <div className="beta-cards">
      <section className="card" aria-labelledby="beta-title">
        <h2 id="beta-title" className="ui-card-title">
          {t("settings_home.beta.title")}
        </h2>
        <p>{t("settings_home.beta.text")}</p>
        <p>
          <a className="ui-button ui-button-primary" href={FEEDBACK_URL} target="_blank" rel="noreferrer">
            {t("settings_home.beta.feedback")}
          </a>
        </p>
      </section>
      <section className="card" aria-labelledby="support-title">
        <h2 id="support-title" className="ui-card-title">
          {t("settings_home.support.title")}
        </h2>
        <p>{t("settings_home.support.text")}</p>
        <SupportLinks />
      </section>
    </div>
  );
}
