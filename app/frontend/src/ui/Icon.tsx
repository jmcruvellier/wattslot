// Icônes en ligne (lot 6b.1) : couleur du texte. Décoratives (aria-hidden) : le nom de l'action
// est porté par le bouton ou le lien qui les contient.

import { PATHS, type IconName } from "./iconPaths";

export default function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
