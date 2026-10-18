// Ligne de réglage (lot 6b.1) : libellé, aide d'une ligne, et soit un contrôle à droite, soit une
// flèche quand la ligne ouvre un écran. Les lignes se rangent dans un SettingList.

import type { ReactNode } from "react";

import Icon from "./Icon";

interface SettingRowProps {
  label: string;
  description?: string;
  onOpen?: () => void;
  children?: ReactNode;
}

export function SettingList({ children }: { children: ReactNode }) {
  return <div className="ui-setting-list">{children}</div>;
}

export default function SettingRow({ label, description, onOpen, children }: SettingRowProps) {
  const text = (
    <span>
      <span className="ui-row-label">{label}</span>
      {description && <span className="ui-row-help">{description}</span>}
    </span>
  );
  if (onOpen) {
    return (
      <button type="button" className="ui-setting-row ui-setting-row-open" onClick={onOpen}>
        {text}
        <Icon name="chevron-right" size={18} />
      </button>
    );
  }
  return (
    <div className="ui-setting-row">
      {text}
      {children}
    </div>
  );
}
