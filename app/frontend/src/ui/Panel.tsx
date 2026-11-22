// Panneau : carte à petit titre (icône, nom, et à droite une pastille), pour les écrans denses
// (Aujourd'hui, Planning). Le contenu suit, en lignes « libellé, valeur » ou en tuiles. La carte
// (`Card`) garde son grand titre pour les écrans où une carte porte un message.

import { useId, type ReactNode } from "react";

import Icon from "./Icon";
import type { IconName } from "./iconPaths";

interface PanelProps {
  icon?: IconName;
  title: string;
  meta?: ReactNode; // coin droit de l'en-tête : tendance, qualité, bouton
  level?: 2 | 3;
  className?: string;
  children: ReactNode;
}

export default function Panel({ icon, title, meta, level = 2, className, children }: PanelProps) {
  const Heading = level === 2 ? "h2" : "h3";
  const id = useId();
  return (
    <section className={["ui-card ui-panel", className].filter(Boolean).join(" ")} aria-labelledby={id}>
      <div className="ui-panel-head">
        <Heading id={id} className="ui-panel-title">
          {icon && <Icon name={icon} size={16} />}
          {title}
        </Heading>
        {meta}
      </div>
      {children}
    </section>
  );
}
