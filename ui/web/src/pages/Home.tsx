import { CaseList } from "../components/CaseList";
import { Events } from "../components/Events";
import { Icon } from "../components/Icon";
import { Dot, Section, Tile } from "../components/ui";
import { activity, status, totals } from "../model";
import { day, money, percent } from "../money";
import { Link } from "../router";
import { useStore } from "../store";

const TODAY = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

export function Home() {
  const { state } = useStore();
  const t = totals(state.cases, state.protections);
  const waiting = state.cases.filter((c) => ["needs_you", "held"].includes(status(c).key));
  const funded = state.cases.filter((c) => status(c).key === "funded");
  const next = funded.map((c) => c.flow.ocr).sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  return (
    <>
      <div className="head">
        <div>
          <h1 tabIndex={-1}>Home</h1>
          <p>{TODAY.format(new Date())} · everything the agent does for you, in one place.</p>
        </div>
        <Link to="/get-cash" className="btn btn-primary">
          <Icon name="upload" />
          Get cash for an invoice
        </Link>
      </div>

      {waiting.length > 0 && (
        <div className="banner" role="status">
          <Dot tone="warn" icon="bell" />
          <div className="text">
            <b>
              {waiting.length === 1 ? "One invoice needs" : `${waiting.length} invoices need`} your attention.
            </b>
            <div>Nothing moves on {waiting.length === 1 ? "it" : "them"} until you decide.</div>
          </div>
          <Link to="/needs-you" className="btn btn-ghost">
            Review
          </Link>
        </div>
      )}

      {state.cases.length === 0 ? (
        <section className="card empty">
          <Dot tone="info" icon="upload" />
          <h2 style={{ fontSize: 20 }}>Turn an unpaid invoice into cash today</h2>
          <p className="muted" style={{ maxWidth: 520 }}>
            Upload an invoice you sent to a customer. We check it, find the best lender inside your rule, and pay
            you up to {percent(state.mandate.max_ltv)} of it now.
          </p>
          <Link to="/get-cash" className="btn btn-primary btn-lg">
            Get cash for your first invoice
          </Link>
        </section>
      ) : (
        <div className="tiles">
          <Tile label="Received" value={money(t.received)} valueClass="good" sub={`${funded.length} invoice${funded.length === 1 ? "" : "s"} funded`} />
          <Tile label="Coming when buyers pay" value={money(t.coming)} sub={next ? `${next.buyer.name}, due ${day(next.due_date)}` : "Nothing outstanding"} />
          <Tile label="Cost of financing" value={money(t.fees)} sub="Paid from your buyers' payments" />
        </div>
      )}

      <div className="two">
        <div className="grow">
          {state.cases.length > 0 && (
            <Section title="Your invoices" action={<Link to="/invoices">All invoices</Link>}>
              <CaseList cases={state.cases.slice(0, 5)} />
            </Section>
          )}
          <Section title="Recent activity" action={<Link to="/activity">Money &amp; activity</Link>}>
            <Events events={activity(state.cases, state.protections).slice(0, 5)} empty="Nothing yet. Your first invoice will show here." />
          </Section>
        </div>
        <div className="aside">
          <Section title="Your rule" action={<Link to="/rule">Edit</Link>}>
            <p style={{ lineHeight: 1.55 }}>{state.ruleText}</p>
            <div className="sec">
              <span className="help">Active until {day(state.mandate.expires_at)}</span>
              <span className="chip ok">Signed</span>
            </div>
          </Section>
          <Section title="You are protected" action={<Link to="/activity">See all</Link>}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Dot tone="ok" icon="shield" />
              <div>
                <b style={{ fontSize: 20 }}>
                  {t.blocked} attempt{t.blocked === 1 ? "" : "s"} blocked
                </b>
                <div className="help">No money moved on any of them</div>
              </div>
            </div>
            <p className="help">Unknown payees, duplicate invoices and over-limit draws are refused by the wallet before anything is signed.</p>
          </Section>
        </div>
      </div>
    </>
  );
}
