import { useState } from "react";
import { Icon } from "../components/Icon";
import { Chip, Dot, Kv } from "../components/ui";
import { advance, type Case, status } from "../model";
import { day, money } from "../money";
import { Link } from "../router";
import { useStore } from "../store";

export function NeedsYou() {
  const { state } = useStore();
  const waiting = state.cases.filter((c) => ["needs_you", "held"].includes(status(c).key));
  return (
    <>
      <div className="head">
        <div>
          <h1 tabIndex={-1}>Needs you</h1>
          <p>Invoices the agent stopped on. Nothing moves on them until you decide.</p>
        </div>
      </div>
      {waiting.length === 0 ? (
        <section className="card empty">
          <Dot tone="ok" icon="check" />
          <h2 style={{ fontSize: 20 }}>Nothing needs you</h2>
          <p className="muted">The agent is working inside your rule. You will see an invoice here when a check fails or a draw reaches your ask-me limit.</p>
          <Link to="/rule" className="btn btn-ghost">
            See my rule
          </Link>
        </section>
      ) : (
        waiting.map((c) => <Waiting key={c.id} c={c} />)
      )}
    </>
  );
}

function Waiting({ c }: { c: Case }) {
  const store = useStore();
  const s = status(c);
  const inv = c.flow.ocr;
  const adv = advance(c.flow);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function approve() {
    setBusy(true);
    try {
      setNote(await store.confirm(c.id));
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby={`h-${c.id}`}>
      <div className="sec" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        <div>
          <h2 id={`h-${c.id}`} style={{ fontSize: 20 }}>
            {s.key === "held" ? `We held ${inv.invoice_no}` : `Approve ${inv.invoice_no} once?`}
          </h2>
          <p className="help">
            {inv.buyer.name} · {money(inv.amount, inv.currency)} · due {day(inv.due_date)}
          </p>
        </div>
        <Chip tone={s.tone}>{s.label}</Chip>
      </div>
      <ul className="checks">
        {s.why.map((w) => (
          <li key={w} className="check warn">
            <Icon name="alert" />
            <span>
              <b>{w}</b>
            </span>
          </li>
        ))}
      </ul>
      {s.key === "needs_you" && adv !== null && (
        <div>
          <Kv k="You would get today" v={<span className="brand">{money(adv)}</span>} />
          <Kv k="Your ask-me limit" v={money(store.state.mandate.human_review_above)} />
        </div>
      )}
      {s.key === "held" && <p className="help">Nothing was financed and you were not charged. If the file was wrong, upload a corrected one.</p>}
      {note && (
        <div className="notice" role="status">
          {note}
        </div>
      )}
      <div className="actions">
        {s.key === "needs_you" ? (
          <>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void approve()}>
              {busy ? "Approving…" : "Approve this once"}
            </button>
            <button type="button" className="btn btn-danger" onClick={() => store.setOwner(c.id, "declined")}>
              Decline
            </button>
          </>
        ) : (
          <>
            <Link to="/get-cash" className="btn btn-primary">
              Upload a corrected invoice
            </Link>
            <button type="button" className="btn btn-ghost" onClick={() => store.setOwner(c.id, "closed")}>
              Close it
            </button>
          </>
        )}
        <Link to={`/invoice/${c.id}`}>See the details</Link>
      </div>
    </section>
  );
}
