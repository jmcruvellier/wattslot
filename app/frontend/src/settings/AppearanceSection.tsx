// Section « Langue et affichage » des réglages (lots 6b.1 et 6b.2) : langue de l'interface et
// thème, gardés sur cet appareil et appliqués tout de suite, sans passer par « Enregistrer ».

import { useI18n } from "../i18n/I18nProvider";
import { LANGUAGE_NAMES, reviewed, SUPPORTED_LANGUAGES } from "../i18n/translate";
import { useTheme } from "../theme/theme";
import ThemePicker from "../ui/ThemePicker";

export default function AppearanceSection() {
  const { language, setLanguage, t } = useI18n();
  const [theme, setTheme] = useTheme();
  return (
    <>
      <h3 id="appearance">{t("settings.appearance.title")}</h3>
      <label>
        {t("app.language")}{" "}
        <select value={language} onChange={(event) => setLanguage(event.target.value as typeof language)}>
          {SUPPORTED_LANGUAGES.map((code) => (
            <option key={code} value={code}>
              {reviewed(code) ? LANGUAGE_NAMES[code] : t("app.to_review", { name: LANGUAGE_NAMES[code] })}
            </option>
          ))}
        </select>
      </label>
      <ThemePicker value={theme} onChange={setTheme} />
      <p className="dim">{t("settings.appearance.help")}</p>
    </>
  );
}
