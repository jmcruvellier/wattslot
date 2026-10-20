// Feuille d'un réglage de « Ma maison » : une copie de la configuration, modifiée par l'éditeur du
// réglage, puis enregistrée entière (/api/configuration). Fermer sans enregistrer abandonne la copie.

import { useState, type ReactNode } from "react";

import { ApiError, putJson } from "../api";
import { useI18n } from "../i18n/I18nProvider";
import Button from "../ui/Button";
import Sheet from "../ui/Sheet";
import type { Configuration, ConfigurationIssue } from "./configuration";

type SaveState =
  | { status: "idle" | "saving" | "failed" }
  | { status: "invalid"; issues: ConfigurationIssue[] };

export default function SettingsSheet({
  title,
  configuration,
  names,
  onClose,
  onSaved,
  children,
}: {
  title: string;
  configuration: Configuration;
  names: Map<string, string>; // nom des équipements, pour les anomalies
  onClose: () => void;
  onSaved: (saved: Configuration) => void;
  children: (draft: Configuration, change: (next: Configuration) => void) => ReactNode;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(configuration);
  const [save, setSave] = useState<SaveState>({ status: "idle" });

  const change = (next: Configuration) => {
    setSave({ status: "idle" });
    setDraft(next);
  };

  const onSave = async () => {
    setSave({ status: "saving" });
    try {
      onSaved(await putJson<Configuration>("api/configuration", draft));
    } catch (error) {
      if (error instanceof ApiError && error.status === 422 && Array.isArray(error.detail)) {
        setSave({ status: "invalid", issues: error.detail as ConfigurationIssue[] });
      } else {
        setSave({ status: "failed" });
      }
    }
  };

  return (
    <Sheet open wide title={title} onClose={onClose}>
      {children(draft, change)}
      <div className="home-sheet-actions">
        {save.status === "failed" && <p role="alert">{t("configuration.save_failed")}</p>}
        {save.status === "invalid" && (
          <ul role="alert">
            {save.issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`} className="issue">
                {t(`configuration.issue.${issue.code}`, {
                  ...issue.params,
                  device: names.get(issue.device ?? "") ?? issue.device ?? "",
                })}
              </li>
            ))}
          </ul>
        )}
        <Button variant="primary" onClick={() => void onSave()} disabled={save.status === "saving"}>
          {t("configuration.save")}
        </Button>
      </div>
    </Sheet>
  );
}
