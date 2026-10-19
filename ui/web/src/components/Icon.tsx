const PATHS = {
  home: ["M3 11l9-8 9 8", "M5 10v10h14V10"],
  upload: ["M12 16V4", "M6 10l6-6 6 6", "M4 20h16"],
  download: ["M12 4v12", "M6 10l6 6 6-6", "M4 20h16"],
  invoice: ["M6 3h8l4 4v14H6z", "M14 3v4h4", "M9 13h6M9 17h6"],
  bell: ["M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z", "M10 21h4"],
  rule: ["M4 7h16M4 17h16", "M9 4.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5", "M15 14.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5"],
  wallet: ["M5 6h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2", "M16 12.5h5", "M3 10h18"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  cross: ["M7 7l10 10M17 7L7 17"],
  clock: ["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18", "M12 7v5l3 2"],
  alert: ["M12 3l10 18H2z", "M12 10v4", "M12 17.5v.5"],
  shield: ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z", "M9 12l2 2 4-4"],
  back: ["M15 6l-6 6 6 6"],
  next: ["M9 6l6 6-6 6"],
  file: ["M6 3h8l4 4v14H6z", "M14 3v4h4"],
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = "ic" }: { name: IconName; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
