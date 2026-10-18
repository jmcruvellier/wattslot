// Écran de démonstration des composants (lot 6b.1), hors du menu, à l'adresse #/ui : chaque
// composant de base dans chaque thème, côte à côte, pour les contrôler d'un coup d'œil.

import { useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { THEMES, type Theme } from "../theme/theme";
import Button from "./Button";
import Card from "./Card";
import Icon from "./Icon";
import { ICON_NAMES } from "./iconPaths";
import SettingRow, { SettingList } from "./SettingRow";
import Sheet from "./Sheet";
import Switch from "./Switch";

function ThemePanel({ theme }: { theme: Exclude<Theme, "auto"> }) {
  const { t } = useI18n();
  const [on, setOn] = useState(true);
  const [sheet, setSheet] = useState(false);
  return (
    <section className="ui-gallery-theme" data-theme={theme} aria-label={t(`settings.appearance.themes.${theme}.name`)}>
      <h2>{t(`settings.appearance.themes.${theme}.name`)}</h2>
      <Card eyebrow={t("ui.card_eyebrow")} title={t("ui.card_title")} level={3}>
        <p>{t("ui.card_body")}</p>
      </Card>
      <div className="ui-gallery-row">
        <Card tone="sun">
          <strong>{t("ui.sun")}</strong>
        </Card>
        <Card tone="battery">
          <strong>{t("ui.battery")}</strong>
        </Card>
      </div>
      <div className="ui-gallery-row">
        <Button variant="primary" icon="check">
          {t("ui.primary")}
        </Button>
        <Button>{t("ui.secondary")}</Button>
        <Button variant="quiet">{t("ui.quiet")}</Button>
      </div>
      <SettingList>
        <SettingRow label={t("ui.row")} description={t("ui.row_help")} onOpen={() => setSheet(true)} />
        <Switch label={t("ui.switch")} description={t("ui.switch_help")} checked={on} onChange={setOn} />
      </SettingList>
      <div className="ui-gallery-row">
        {ICON_NAMES.map((name) => (
          <Icon key={name} name={name} />
        ))}
      </div>
      <Sheet open={sheet} title={t("ui.sheet_title")} onClose={() => setSheet(false)}>
        <p>{t("ui.sheet_body")}</p>
        <Button variant="primary" onClick={() => setSheet(false)}>
          {t("ui.primary")}
        </Button>
      </Sheet>
    </section>
  );
}

export default function UiGallery() {
  const { t } = useI18n();
  return (
    <section aria-labelledby="ui-gallery-title">
      <h2 id="ui-gallery-title">{t("ui.title")}</h2>
      <p>{t("ui.intro")}</p>
      <div className="ui-gallery">
        {THEMES.filter((theme): theme is Exclude<Theme, "auto"> => theme !== "auto").map((theme) => (
          <ThemePanel key={theme} theme={theme} />
        ))}
      </div>
    </section>
  );
}
