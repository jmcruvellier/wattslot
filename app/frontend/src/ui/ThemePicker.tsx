// Choix du thème (lot 6b.1) : « Automatique » et les cinq thèmes ; chaque pastille montre le fond
// et la couleur d'action de son thème, quel que soit le thème affiché.

import { useI18n } from "../i18n/I18nProvider";
import { THEMES, type Theme } from "../theme/theme";

interface ThemePickerProps {
  value: Theme;
  onChange: (theme: Theme) => void;
}

export default function ThemePicker({ value, onChange }: ThemePickerProps) {
  const { t } = useI18n();
  return (
    <fieldset className="theme-picker">
      <legend>{t("settings.appearance.theme")}</legend>
      {THEMES.map((name) => (
        <label key={name} className={`theme-option theme-option-${name}`}>
          <input type="radio" name="theme" value={name} checked={value === name} onChange={() => onChange(name)} />
          <span className="theme-swatch" aria-hidden="true" />
          <span>
            <strong>{t(`settings.appearance.themes.${name}.name`)}</strong>
            <small>{t(`settings.appearance.themes.${name}.help`)}</small>
          </span>
        </label>
      ))}
    </fieldset>
  );
}
