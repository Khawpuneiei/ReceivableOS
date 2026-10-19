import { useState } from "react";
import { Checks, Facts, Receipts, advanceRate, ratePct } from "../components/flow";
import { Icon } from "../components/Icon";
import { Chip, Kv, Section, Steps } from "../components/ui";
import { advance, type Case, chosenOffer, fee, onPayment, ruleChecks, status } from "../model";
import { day, money, percent, plus, times } from "../money";
import { Link } from "../router";
import { useStore } from "../store";

export function Invoice({ id }: { id?: string }) {
  const store = useStore();
  const c = store.state.cases.find((x) => x.id === id);
  if (!c) {
    return (
      <section className="card empty">
        <h1 tabIndex={-1}>Invoice not found</h1>
        <p className="muted">It is not in this tab's history. Your invoices are listed on the Invoices page.</p>
        <Link to="/invoices" className="btn btn-primary">
          See invoices
        </Link>
      </section>
    );
  }
  return <Result c={c} />;
}

function Result({ c }: { c: Case }) {
  const store = useStore();
  const { flow } = c;
  const inv = flow.ocr;
  const s = status(c);
  const p = flow.policy;
  const adv = advance(flow);
  const f = fee(flow);
  const rest = onPayment(flow);
  const offer = chosenOffer(flow);
  const [paying, setPaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function simulatePayment() {
    setPaying(true);
    setError(null);
    try {
      await store.repay(c.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPaying(false);
    }
  }

  const stopped = s.key === "declined" || s.key === "held" || s.key === "stopped" || s.key === "closed";
  return (
    <>
      <div>
        <div className="crumb">
          <Link to="/invoices">Invoices</Link> / {inv.invoice_no}
        </div>
        <Steps at={4} />
      </div>

      <section className="card hero">
        <div className="text">
          <span style={{ alignSelf: "flex-start" }}>
            <Chip tone={s.tone}>{s.key === "funded" ? "All checks passed · inside your rule" : s.label}</Chip>
          </span>
          {s.key === "funded" && adv !== null && (
            <>
              <h1 tabIndex={-1}>
                You got <em>{money(adv)}</em>
              </h1>
              <p className="lead">
                That is {ratePct(advanceRate(flow))} of invoice {inv.invoice_no} ({money(inv.amount)}) to {inv.buyer.name}.
                {f !== null && rest !== null && ` The rest, less a fee of ${money(f)}, arrives when they pay on ${day(inv.due_date)}.`}
              </p>
              <p className="help">Your rule let the agent take the best quote for you. Nothing needed your approval.</p>
            </>
          )}
          {s.key === "paid" && adv !== null && rest !== null && (
            <>
              <h1 tabIndex={-1}>
                Paid in full: you received <em>{money(adv + rest)}</em>
              </h1>
              <p className="lead">
                {inv.buyer.name} paid {money(inv.amount)}. The lender was repaid with the fee of {money(f ?? 0n)}, and {money(rest)} came to you.
              </p>
            </>
          )}
          {s.key === "needs_you" && (
            <>
              <h1 tabIndex={-1}>
                Approve once to get <em>{adv === null ? "your advance" : money(adv)}</em>
              </h1>
              <p className="lead">This invoice is above your ask-me limit. Every other check passed. Nothing moves until you say so.</p>
            </>
          )}
          {stopped && (
            <>
              <h1 tabIndex={-1}>{s.key === "held" ? "We held this invoice" : "We could not finance this invoice"}</h1>
              <ul className="lead" style={{ margin: 0, paddingLeft: 20 }}>
                {s.why.map((w) => (
                  <li key={w}>{w}.</li>
                ))}
              </ul>
              <p className="help">Nothing was financed, nothing was signed, and you were not charged.</p>
            </>
          )}
        </div>
        <div className="cta">
          {s.key === "needs_you" && (
            <Link to="/needs-you" className="btn btn-primary btn-lg">
              Review and approve
            </Link>
          )}
          {s.key === "held" && (
            <>
              <Link to="/get-cash" className="btn btn-primary btn-lg">
                Upload a corrected invoice
              </Link>
              <button type="button" className="btn btn-ghost" onClick={() => store.setOwner(c.id, "closed")}>
                Close it
              </button>
            </>
          )}
          {(s.key === "funded" || s.key === "paid") && (
            <Link to="/activity" className="btn btn-primary btn-lg">
              See it in your money
            </Link>
          )}
          {s.key !== "held" && s.key !== "needs_you" && (
            <Link to="/get-cash" className="btn btn-ghost">
              Get cash for another invoice
            </Link>
          )}
        </div>
      </section>

      {error && (
        <div className="notice bad" role="alert">
          {error}
        </div>
      )}

      <div className="two">
        <div className="grow">
          {p?.decision === "approve" && adv !== null && (
            <Section title="Your money, step by step">
              <div>
                <Kv k="Invoice total" v={money(inv.amount)} />
                <Kv k={`Today, ${ratePct(advanceRate(flow))} advance`} v={<span className="brand">{money(adv)}</span>} />
                {f !== null && (
                  <Kv
                    k={`Fee for ${p.tenor_days ?? "-"} days (${percent(p.fee_rate)} per 30 days${offer?.apr ?? p.apr ? `, ${percent(offer?.apr ?? p.apr ?? "0")} a year` : ""})`}
                    v={money(f)}
                  />
                )}
                {rest !== null && <Kv k={`When ${inv.buyer.name} pays, ${day(inv.due_date)}`} v={money(rest)} />}
                {rest !== null && <Kv strong k="You receive in total" v={money(adv + rest)} />}
              </div>
            </Section>
          )}

          {flow.offers && flow.offers.length > 0 && (
            <Section title={`We compared ${flow.offers.length} lenders`}>
              {flow.offers.map((o) => {
                const today = times(inv.amount, o.advance_rate);
                const gap = adv !== null ? adv - today : 0n;
                const why = o.chosen
                  ? "Most cash today within your cost cap"
                  : !o.within_mandate
                    ? "Costs more than your rule allows"
                    : gap > 0n
                      ? `Cheaper, but ${money(gap)} less today`
                      : "Not chosen";
                return (
                  <div key={o.lender} className={`offer${o.chosen ? " chosen" : ""}`}>
                    <div className="what">
                      <b>{o.lender}</b> {o.chosen && <Chip tone="info">Chosen</Chip>}
                      <div>{why}</div>
                    </div>
                    <div className="terms">
                      <b>
                        {percent(o.advance_rate)} · {money(today)}
                      </b>
                      <div>{percent(o.apr)} a year</div>
                    </div>
                  </div>
                );
              })}
            </Section>
          )}

          {s.key === "funded" && (
            <Section title="What happens next">
              <div className="list">
                <div className="item">
                  <span className="dot d-ok" aria-hidden="true">
                    <Icon name="check" />
                  </span>
                  <div className="what">
                    <b>Done</b>
                    <div>{adv !== null && money(adv)} went to your verified account, with a receipt on the ledger.</div>
                  </div>
                </div>
                <div className="item">
                  <span className="dot d-info" aria-hidden="true">
                    <Icon name="clock" />
                  </span>
                  <div className="what">
                    <b>{day(inv.due_date)}</b>
                    <div>{inv.buyer.name} pays {money(inv.amount)} into the financing vault, not to the lender directly.</div>
                  </div>
                </div>
                <div className="item">
                  <span className="dot d-info" aria-hidden="true">
                    <Icon name="wallet" />
                  </span>
                  <div className="what">
                    <b>Same day</b>
                    <div>The lender is repaid with the fee, and {rest !== null && money(rest)} comes to you automatically.</div>
                  </div>
                </div>
              </div>
              <div className="actions">
                <button type="button" className="btn btn-ghost" disabled={paying} onClick={() => void simulatePayment()}>
                  {paying ? "Recording the payment…" : `Demo: ${inv.buyer.name} pays today`}
                </button>
                <span className="help">For the demo only: settles the invoice now instead of on the due date.</span>
              </div>
            </Section>
          )}

          <Section title="How we checked it">
            <Checks flow={flow} />
          </Section>
        </div>

        <aside className="aside">
          {p?.decision === "approve" && (
            <Section title="Inside your rule" action={<Link to="/rule">My rule</Link>}>
              <ul className="checks">
                {ruleChecks(flow, store.state.mandate).map(([title, detail]) => (
                  <li key={title} className={`check ${title.startsWith("Above") ? "warn" : "pass"}`}>
                    <Icon name={title.startsWith("Above") ? "alert" : "check"} />
                    <span>
                      <b>{title}</b>
                      <div>{detail}</div>
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          <Section title="What we read">
            <Facts flow={flow} />
          </Section>
          <Section title="Receipts">
            <Receipts flow={flow} settled={c.settlement} />
            {p?.limit && <span className="help">Approved limit {money(plus(p.limit))}.</span>}
          </Section>
        </aside>
      </div>
    </>
  );
}
