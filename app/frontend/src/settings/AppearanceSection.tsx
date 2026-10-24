// Section « Langue et affichage » des réglages (lots 6b.1 et 6b.2) : langue de l'interface et
// thème, gardés sur cet appareil et appliqués tout de suite, sans passer par « Enregistrer ».
// Devise de la maison (lot 7.3) : enregistrée par le serveur, pour tous les appareils.

import { useState } from "react";

import { Hint } from "../common/Advanced";
import { useCurrency } from "../i18n/currency";
import { useI18n } from "../i18n/I18nProvider";
import { LANGUAGE_NAMES, reviewed, SUPPORTED_LANGUAGES } from "../i18n/translate";
import { useChartLegends } from "../plan/legends";
import { useTheme } from "../theme/theme";
import Switch from "../ui/Switch";
import ThemePicker from "../ui/ThemePicker";

export default function AppearanceSection() {
  const { language, setLanguage, t } = useI18n();
  const [theme, setTheme] = useTheme();
  const [legends, setLegends] = useChartLegends();
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
      <CurrencyPicker />
      <ThemePicker value={theme} onChange={setTheme} />
      <Switch
        label={t("settings.appearance.legends")}
        description={t("settings.appearance.legends_help")}
        checked={legends}
        onChange={setLegends}
      />
      <p className="dim">{t("settings.appearance.help")}</p>
    </>
  );
}

function CurrencyPicker() {
  const { language, t } = useI18n();
  const { state, save } = useCurrency();
  const [failed, setFailed] = useState(false);
  if (state === null) return null;
  const name = (code: string) =>
    new Intl.DisplayNames(language, { type: "currency" }).of(code) ?? code;
  const choices = state.code && !state.choices.includes(state.code) ? [...state.choices, state.code] : state.choices;
  const change = (value: string) => {
    setFailed(false);
    save(value === "" ? null : value).catch(() => setFailed(true));
  };
  return (
    <p>
      <label>
        {t("settings.currency.label")}{" "}
        <select value={state.code ?? ""} onChange={(event) => change(event.target.value)}>
          <option value="">
            {state.home_assistant
              ? t("settings.currency.automatic", { name: name(state.home_assistant) })
              : t("settings.currency.automatic_default", { name: name("EUR") })}
          </option>
          {choices.map((code) => (
            <option key={code} value={code}>
              {name(code)} ({code})
            </option>
          ))}
        </select>
      </label>
      <Hint text={t("settings.currency.hint")} />
      {failed && <span role="alert"> {t("settings.currency.failed")}</span>}
    </p>
  );
}
