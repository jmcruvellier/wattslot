// Interrupteur (lot 6b.1) : bouton au rôle « switch », Espace et Entrée l'actionnent comme tout
// bouton. Le nom vient du libellé visible, relié par aria-labelledby.

import { useId } from "react";

interface SwitchProps {
  label: string;
  description?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}

export default function Switch({ label, description, checked, disabled, onChange }: SwitchProps) {
  const id = useId();
  return (
    <div className="ui-switch-row">
      <span>
        <span id={`${id}-label`} className="ui-row-label">
          {label}
        </span>
        {description && (
          <span id={`${id}-help`} className="ui-row-help">
            {description}
          </span>
        )}
      </span>
      <button
        type="button"
        role="switch"
        className="ui-switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={description ? `${id}-help` : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span className="ui-switch-thumb" aria-hidden="true" />
      </button>
    </div>
  );
}
