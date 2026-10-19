import type { ReactNode } from "react";
import type { Tone } from "../model";
import { Icon, type IconName } from "./Icon";

export const Chip = ({ tone, children }: { tone: Tone; children: ReactNode }) => (
  <span className={`chip ${tone}`}>{children}</span>
);

export const Tile = ({ label, value, sub, valueClass }: { label: string; value: ReactNode; sub?: ReactNode; valueClass?: string }) => (
  <div className="tile">
    <span className="lbl">{label}</span>
    <b className={valueClass}>{value}</b>
    {sub && <span className="sub">{sub}</span>}
  </div>
);

export const Kv = ({ k, v, strong }: { k: ReactNode; v: ReactNode; strong?: boolean }) => (
  <div className={`kv${strong ? " total" : ""}`}>
    <span>{k}</span>
    <b>{v}</b>
  </div>
);

const DOT: Record<string, [string, IconName]> = {
  ok: ["d-ok", "check"],
  bad: ["d-bad", "cross"],
  warn: ["d-warn", "alert"],
  info: ["d-info", "clock"],
};

export const Dot = ({ tone, icon }: { tone: "ok" | "bad" | "warn" | "info"; icon?: IconName }) => (
  <span className={`dot ${DOT[tone][0]}`} aria-hidden="true">
    <Icon name={icon ?? DOT[tone][1]} />
  </span>
);

export const Section = ({ title, action, children, className = "" }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) => (
  <section className={`card ${className}`}>
    <div className="sec">
      <h2>{title}</h2>
      {action}
    </div>
    {children}
  </section>
);

export function Steps({ at }: { at: 1 | 2 | 3 | 4 }) {
  const steps = ["Upload", "We check it", "Your result"];
  return (
    <ol className="steps" aria-label="Progress">
      {steps.map((s, i) => {
        const n = i + 1;
        const cls = n < at ? "done" : n === at ? "now" : "";
        return (
          <li key={s} className={cls} aria-current={n === at ? "step" : undefined}>
            <i aria-hidden="true">{n < at ? <Icon name="check" /> : n}</i>
            {s}
          </li>
        );
      })}
    </ol>
  );
}
