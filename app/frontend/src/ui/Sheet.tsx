// Feuille (lot 6b.1) : monte du bas de l'écran sur téléphone, fenêtre centrée sur ordinateur
// (styles.css). Fenêtre modale : le focus y entre à l'ouverture, Tab y reste, Échap ou un clic à
// côté la ferment, et le focus revient à l'élément qui l'a ouverte.

import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../i18n/I18nProvider";
import Icon from "./Icon";

interface SheetProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function Sheet({ open, title, onClose, children }: SheetProps) {
  const { t } = useI18n();
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  // Dernière fonction de fermeture, sans relancer l'effet (et voler le focus) à chaque rendu.
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusable = () => [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    // Premier champ ou bouton après celui de fermeture, sinon la fermeture.
    const [closeButton, first] = focusable();
    (first ?? closeButton)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) return;
      const [head, tail] = [items[0], items[items.length - 1]];
      if (event.shiftKey && document.activeElement === head) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault();
        head.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div className="ui-sheet-backdrop" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={panel} className="ui-sheet" role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="ui-sheet-header">
          <h2 id={id}>{title}</h2>
          <button type="button" className="ui-icon-button" aria-label={t("ui.close")} onClick={onClose}>
            <Icon name="close" size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
