import { useState } from "react";
import { Events } from "../components/Events";
import { Section } from "../components/ui";
import { activity } from "../model";
import { day, money, percent, toMicros } from "../money";
import { Link } from "../router";
import { useStore } from "../store";
import type { Mandate } from "../types";

/** "0.70" -> 70 (whole percent, for a slider). */
const toPct = (rate: string) => Number((toMicros(rate) * 100n) / 1_000_000n);
/** 70 -> "0.70". */
const fromPct = (n: number) => {
  const s = String(Math.round(n)).padStart(3, "0");
  return `${s.slice(0, -2)}.${s.slice(-2)}`;
};

/** "837500" or "837500.5" -> "837500.00" / "837500.50". */
const toCents = (v: string) => {
  const [whole, frac = ""] = v.split(".");
  return `${whole}.${frac.padEnd(2, "0")}`;
};

/** The sentence that gets signed, in the form the deterministic mandate compiler reads. */
export const ruleSentence = (m: Mandate) =>
  `Finance my approved invoices automatically, but never advance more than ${percent(m.max_ltv)}, never pay more than ` +
  `${percent(m.max_apr)} APR, stop if buyer risk is above ${percent(m.max_predicted_default)}, and ask me above ` +
  `${money(m.human_review_above).replace(/\.00$/, "")}.`;

const SLIDERS: { key: "max_ltv" | "max_apr" | "max_predicted_default"; label: string; min: number; max: number; step: number; help: string }[] = [
  { key: "max_ltv", label: "Most I will take up front", min: 50, max: 90, step: 5, help: "Less up front means less cash now and a smaller fee." },
  { key: "max_apr", label: "Most I will pay per year", min: 6, max: 20, step: 1, help: "Lender quotes above this are refused without asking you." },
  { key: "max_predicted_default", label: "Stop if a buyer's chance of not paying is above", min: 1, max: 10, step: 1, help: "Checked for every buyer, on every invoice." },
];

export function Rule() {
  const store = useStore();
  const { mandate } = store.state;
  const [draft, setDraft] = useState<Mandate>(mandate);
  const [ask, setAsk] = useState(mandate.human_review_above);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const askValue = ask.replace(/,/g, "").trim();
  const askOk = /^\d+(\.\d{1,2})?$/.test(askValue) && toMicros(askValue) > 0n;
  const next: Mandate = askOk ? { ...draft, human_review_above: toCents(askValue) } : draft;
  const changed = JSON.stringify(next) !== JSON.stringify(mandate);
  const blocked = activity([], store.state.protections).slice(0, 3);

  async function save() {
    setBusy(true);
    try {
      setNote({ text: await store.saveRule(next, ruleSentence(next)) });
    } catch (e) {
      setNote({ text: e instanceof Error ? e.message : String(e), bad: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="head">
        <div>
          <h1 tabIndex={-1}>My rule</h1>
          <p>Set it once. The agent finances invoices inside these limits and asks you about anything outside them.</p>
        </div>
        <span className="chip ok">Signed · active until {day(mandate.expires_at)}</span>
      </div>
      <div className="two">
        <form
          className="card grow"
          style={{ gap: 26 }}
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          {SLIDERS.map((s) => (
            <div className="field" key={s.key}>
              <div className="row">
                <label htmlFor={s.key}>{s.label}</label>
                <span className="val" aria-hidden="true">
                  {percent(draft[s.key])}
                </span>
              </div>
              <input
                id={s.key}
                type="range"
                min={s.min}
                max={s.max}
                step={s.step}
                value={toPct(draft[s.key])}
                aria-valuetext={percent(draft[s.key])}
                onChange={(e) => setDraft({ ...draft, [s.key]: fromPct(Number(e.target.value)) })}
              />
              <span className="help">{s.help}</span>
            </div>
          ))}
          <div className="field">
            <label htmlFor="ask">Ask me before taking more than this on one invoice</label>
            <div className="money-in">
              <span>THB</span>
              <input id="ask" type="text" inputMode="decimal" value={ask} aria-invalid={!askOk} onChange={(e) => setAsk(e.target.value)} />
            </div>
            <span className="help">{askOk ? "Below this, the agent acts alone. At or above it, nothing moves until you approve." : "Enter an amount, like 837500.00."}</span>
          </div>
          <div className="field">
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--ink2)" }}>Your rule in words</span>
            <p className="rule-text">{ruleSentence(next)}</p>
            <span className="help">
              This sentence is what gets signed. Only its fingerprint goes on the ledger, never the sentence. When two lenders qualify,
              the agent takes the one that pays you most within your cost cap.
            </span>
          </div>
          {note && (
            <div className={`notice${note.bad ? " bad" : ""}`} role="status">
              {note.text}
            </div>
          )}
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={!changed || !askOk || busy}>
              {busy ? "Saving…" : "Save and sign"}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={!changed}
              onClick={() => {
                setDraft(mandate);
                setAsk(mandate.human_review_above);
                setNote(null);
              }}
            >
              Undo changes
            </button>
          </div>
        </form>
        <aside className="aside">
          <Section title="Always on">
            <div>
              <div className="kv">
                <span>Pay only to my verified account</span>
                <span className="chip ok">On</span>
              </div>
              <div className="kv">
                <span>Never finance the same invoice twice</span>
                <span className="chip ok">On</span>
              </div>
              <div className="kv">
                <span>One draw, at most</span>
                <b>{money(mandate.max_amount_per_tx)}</b>
              </div>
              <div className="kv">
                <span>One day, at most</span>
                <b>{money(mandate.daily_cap)}</b>
              </div>
            </div>
            <p className="help">Set by the platform. Neither you nor the agent can switch these off.</p>
          </Section>
          <Section title="What the wallet stopped" action={<Link to="/activity">All</Link>}>
            <Events compact events={blocked} empty="Nothing yet. Run the protection test on the Money & activity page to see it work." />
          </Section>
        </aside>
      </div>
    </>
  );
}
