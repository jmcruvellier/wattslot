// Tracés des icônes (lot 6b.1, Icon.tsx) : traits de 2 px sur une grille de 24.

export const PATHS = {
  today: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2" />
    </>
  ),
  planning: (
    <>
      <rect x="3.5" y="5" width="17" height="15" rx="2.5" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </>
  ),
  curves: (
    <>
      <path d="M4 4v16h16" />
      <path d="M7.5 15l3.5-4 3 2.5 5-6" />
    </>
  ),
  home: (
    <>
      <path d="M4 11l8-6.5 8 6.5V20H4z" />
      <path d="M10 20v-5h4v5" />
    </>
  ),
  assistant: <path d="M4 5.5h16v10H9l-5 4z" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" />
    </>
  ),
  battery: (
    <>
      <rect x="3" y="7" width="16" height="10" rx="2" />
      <path d="M21 10.5v3M7 10.5v3" />
    </>
  ),
  plug: <path d="M9 3v5M15 3v5M6.5 8h11v3a5.5 5.5 0 0 1-11 0zM12 16.5V21" />,
  bell: <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5h4" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  plus: <path d="M12 5v14M5 12h14" />,
  cloud: <path d="M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 11 3.5 3.5 0 0 0 7 18z" />,
  "cloud-sun": (
    <>
      <path d="M9 4v1.5M4.5 9H3M5.6 5.6l1 1M13.4 5.6l-1 1" />
      <path d="M12.5 10.2A4 4 0 0 0 6 12" />
      <path d="M9 20h8a3.5 3.5 0 0 0 .4-6.98A5 5 0 0 0 8 13.6 3.2 3.2 0 0 0 9 20z" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  warning: <path d="M12 3.5l9.5 16.5h-19zM12 10v4M12 17h.01" />,
  target: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="0.8" />
    </>
  ),
  bulb: <path d="M9 18h6M10 21h4M8.5 14.5A6 6 0 1 1 15.5 14.5c-.9.8-1.5 1.6-1.5 2.5h-4c0-.9-.6-1.7-1.5-2.5z" />,
  "arrow-up": <path d="M12 20V5M6 11l6-6 6 6" />,
  refresh: <path d="M20 11a8 8 0 0 0-14.3-4.6L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.6L20 16M20 20v-4h-4" />,
  layout: (
    <>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="17" height="7" rx="1.5" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6L6 18" />,
  "chevron-right": <path d="M9 6l6 6-6 6" />,
  "chevron-left": <path d="M15 6l-6 6 6 6" />,
  "menu-collapse": <path d="M4 5v14M20 12H9M13 8l-4 4 4 4" />,
  "menu-expand": <path d="M4 5v14M9 12h11M16 8l4 4-4 4" />,
} as const;

export type IconName = keyof typeof PATHS;
export const ICON_NAMES = Object.keys(PATHS) as IconName[];
