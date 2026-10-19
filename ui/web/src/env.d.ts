/// <reference types="vite/client" />

/** "live" calls the orchestrator through /api; "fixtures" (the default) replays saved responses. */
declare const __UI_MODE__: "live" | "fixtures";
