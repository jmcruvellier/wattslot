// Boutons (lot 6b.1) : principal (couleur d'action du thème), secondaire (surface bordée), discret
// (texte seul). 44 px de haut au moins, pour le doigt.

import type { ButtonHTMLAttributes, ReactNode } from "react";

import Icon from "./Icon";
import type { IconName } from "./iconPaths";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "quiet";
  icon?: IconName;
  children: ReactNode;
}

export default function Button({ variant = "secondary", icon, children, className, ...props }: ButtonProps) {
  return (
    <button type="button" {...props} className={["ui-button", `ui-button-${variant}`, className].filter(Boolean).join(" ")}>
      {icon && <Icon name={icon} size={18} />}
      {children}
    </button>
  );
}
