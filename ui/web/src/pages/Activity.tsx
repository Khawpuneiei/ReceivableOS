import { useState } from "react";
import { Events } from "../components/Events";
import { Icon } from "../components/Icon";
import { Kv, Section, Tile } from "../components/ui";
import { activity, activityCsv, onPayment, status, totals } from "../model";
import { day, money } from "../money";
import { useStore } from "../store";

const TABS = ["Everything", "Money only", "Blocked only"] as const;

export function Activity() {
  const store = useStore();
  const { cases, protections, mandate } = store.state;
  const t = totals(cases, protections);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Everything");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const events = activity(cases, protections).filter(
    (e) => tab === "Everything" || (tab === "Money only" ? e.money : e.tone === "bad"),
  );
  const upcoming = cases.filter((c) => status(c).key === "funded");
  const seller = mandate.payee_allowlist.find((p) => p.startsWith("SELLER:")) ?? "-";
  const saved = protections.some((p) => p.saved);

  async function test() {
    setBusy(true);
    setError(null);
    try {
      await store.testProtections();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([activityCsv(activity(cases, protections))], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "receivableos-activity.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <div className="head">
        <div>
          <h1 tabIndex={-1}>Money &amp; activity</h1>
          <p>Every baht in and out, and every attempt the wallet refused. Each line has a receipt on the ledger.</p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={download} disabled={cases.length + protections.length === 0}>
          <Icon name="download" />
          Receipts (CSV)
        </button>
      </div>
      <div className="tiles">
        <Tile label="Received" value={money(t.received)} valueClass="good" sub="Advances and buyer payments" />
        <Tile label="Fees" value={money(t.fees)} sub="Paid from your buyers' payments" />
        <Tile label="Attempts blocked" value={String(t.blocked)} sub={`${money(0n)} moved · you were never charged`} />
      </div>
      <div className="two">
        <section className="card grow" style={{ gap: 4 }}>
          <div className="filters" role="group" aria-label="Show">
            {TABS.map((x) => (
              <button key={x} type="button" aria-pressed={x === tab} onClick={() => setTab(x)}>
                {x}
              </button>
            ))}
          </div>
          {tab !== "Blocked only" && upcoming.length > 0 && (
            <ul className="list" style={{ listStyle: "none", margin: "12px 0 0", padding: 0 }}>
              {upcoming.map((c) => {
                const rest = onPayment(c.flow);
                return (
                  <li key={c.id} className="item" style={{ background: "var(--bg)", borderRadius: 10, padding: "12px 14px", borderBottom: "none" }}>
                    <span className="dot d-info" aria-hidden="true">
                      <Icon name="clock" />
                    </span>
                    <div className="what">
                      <b>
                        Coming {day(c.flow.ocr.due_date)}: {c.flow.ocr.buyer.name} pays {money(c.flow.ocr.amount)}
                      </b>
                      <div>The lender is repaid with the fee; the rest comes to you the same day.</div>
                    </div>
                    {rest !== null && <span className="amt brand">+ {money(rest)}</span>}
                  </li>
                );
              })}
            </ul>
          )}
          <Events events={events} empty={tab === "Blocked only" ? "Nothing blocked yet." : "Nothing yet. Get cash for an invoice to start."} />
        </section>
        <aside className="aside">
          <Section title="Test your protections">
            <p className="help">
              We try six things a compromised agent or a bad invoice might do: pay an unknown account, finance an invoice twice, take an
              expensive quote, draw too much, skip business verification, act on an expired rule. Each one should be refused.
            </p>
            {error && (
              <div className="notice bad" role="alert">
                {error}
              </div>
            )}
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void test()}>
              {busy ? "Running the six tests…" : "Run the six tests"}
            </button>
            {saved && (
              <p className="help">
                {store.api.mode === "live"
                  ? "Tests the orchestrator does not serve yet were shown from recorded results."
                  : "Sample mode: results recorded from the live stack."}
              </p>
            )}
          </Section>
          <Section title="Where your money goes">
            <div>
              <Kv k="Your verified account" v={<span className="mono">{seller}</span>} />
              <Kv k="Settled in" v="tTHB, 1:1 with THB" />
              <Kv k="Buyers pay into" v="The financing vault" />
            </div>
            <p className="help">Buyers never pay the lender directly. The vault repays the lender first, then pays you the rest.</p>
          </Section>
        </aside>
      </div>
    </>
  );
}
