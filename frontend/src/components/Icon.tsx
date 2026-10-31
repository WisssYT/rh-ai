// A handful of hand-drawn 20x20 stroke icons. Used only where they add meaning.
const PATHS: Record<string, string> = {
  arrow: "M4 10h12M11 5l5 5-5 5",
  back: "M16 10H4M9 5l-5 5 5 5",
  check: "M4 10.5l4 4 8-9",
  close: "M5 5l10 10M15 5L5 15",
  upload: "M10 13V3M6 7l4-4 4 4M4 13v3h12v-3",
  doc: "M6 2.5h6l3 3V17.5H6zM12 2.5v3h3M8 9h5M8 12h5M8 15h3",
  calendar: "M4 5h12v11H4zM4 8.5h12M7.5 3v4M12.5 3v4",
  search: "M8.5 14a5.5 5.5 0 100-11 5.5 5.5 0 000 11zM12.5 12.5L17 17",
  inbox: "M3 11l2.5-7h9L17 11v5H3zM3 11h4l1 2h4l1-2h4",
  people: "M7 9a3 3 0 100-6 3 3 0 000 6zM2 17c.6-3 2.6-4.5 5-4.5s4.4 1.5 5 4.5M13.5 9a2.5 2.5 0 100-5M15 12.5c1.6.4 2.6 1.7 3 4.5",
  grid: "M3 3h6v6H3zM11 3h6v6h-6zM3 11h6v6H3zM11 11h6v6h-6z",
  shield: "M10 2.5l6 2.2v4.6c0 4-2.6 6.8-6 8.2-3.4-1.4-6-4.2-6-8.2V4.7z",
  external: "M11 3h6v6M17 3l-8 8M14 12v4H4V6h4",
  clock: "M10 17.5a7.5 7.5 0 100-15 7.5 7.5 0 000 15zM10 6v4l3 2",
  warn: "M10 3l8 14H2zM10 8v4M10 14.5v.5",
  dot: "M10 11a1 1 0 100-2 1 1 0 000 2z",
};

export function Icon({ name, label, className = "icon" }: { name: keyof typeof PATHS | string; label?: string; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d={PATHS[name] ?? PATHS.dot} />
    </svg>
  );
}

/** Brand mark: a lens resting on two text lines - "reading for evidence". */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden fill="none">
      <path d="M2.5 6.5h9M2.5 10.5h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="14.5" cy="13" r="5.2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M18.3 16.8l3.2 3.2" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M12 13h5" stroke="#f3d35a" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
