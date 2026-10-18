// Réglages progressifs (lot 4.7, point n° 6 de la phase 4) : l'essentiel visible, le reste replié
// sous « Réglages avancés ». Un réglage par défaut est un réglage valable : on peut ne jamais
// déplier. Le bloc s'ouvre de lui-même si un réglage avancé diffère du défaut, pour ne jamais
// cacher une valeur changée.

import { useState, type ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";

export default function Advanced({ modified, children }: { modified: boolean; children: ReactNode }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(modified);
  return (
    <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{t(modified ? "advanced.modified" : "advanced.title")}</summary>
      {children}
    </details>
  );
}

// Aide d'une phrase sous un réglage visible.
export function Hint({ text }: { text: string }) {
  return (
    <>
      <br />
      <small>{text}</small>
    </>
  );
}
