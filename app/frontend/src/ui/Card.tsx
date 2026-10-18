// Carte (lot 6b.1) : surface arrondie, bordure fine, sans ombre. Avec un titre, la carte est une
// section nommée par lui ; « tone » réserve un fond doux au soleil ou à la batterie.

import { useId, type ReactNode } from "react";

interface CardProps {
  title?: string;
  eyebrow?: string;
  tone?: "sun" | "battery";
  level?: 2 | 3; // niveau du titre : 2 en tête d'écran, 3 dans une section titrée
  children: ReactNode;
}

export default function Card({ title, eyebrow, tone, level = 2, children }: CardProps) {
  const Heading = level === 2 ? "h2" : "h3";
  const id = useId();
  const className = ["ui-card", tone && `ui-card-${tone}`].filter(Boolean).join(" ");
  if (!title) return <div className={className}>{children}</div>;
  return (
    <section className={className} aria-labelledby={id}>
      {eyebrow && <p className="ui-eyebrow">{eyebrow}</p>}
      <Heading id={id} className="ui-card-title">
        {title}
      </Heading>
      {children}
    </section>
  );
}
