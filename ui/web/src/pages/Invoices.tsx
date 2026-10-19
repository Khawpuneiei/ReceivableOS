import { useState } from "react";
import { CaseTable } from "../components/CaseTable";
import { Icon } from "../components/Icon";
import { Tile } from "../components/ui";
import { type Case, type StatusKey, status } from "../model";
import { money, plus } from "../money";
import { Link } from "../router";
import { useStore } from "../store";

const FILTERS: { label: string; keys: StatusKey[] | null }[] = [
  { label: "All", keys: null },
  { label: "Needs you", keys: ["needs_you", "held"] },
  { label: "Funded", keys: ["funded"] },
  { label: "Paid", keys: ["paid"] },
  { label: "Declined", keys: ["declined", "closed", "stopped"] },
];

const sum = (cases: Case[]) => plus(...cases.map((c) => c.flow.ocr.amount));

export function Invoices() {
  const { state } = useStore();
  const [filter, setFilter] = useState(0);
  const [query, setQuery] = useState("");
  const by = (keys: StatusKey[]) => state.cases.filter((c) => keys.includes(status(c).key));
  const keys = FILTERS[filter].keys;
  const q = query.trim().toLowerCase();
  const shown = state.cases.filter(
    (c) =>
      (!keys || keys.includes(status(c).key)) &&
      (!q || `${c.flow.ocr.invoice_no} ${c.flow.ocr.buyer.name}`.toLowerCase().includes(q)),
  );
  return (
    <>
      <div className="head">
        <div>
          <h1 tabIndex={-1}>Invoices</h1>
          <p>Every invoice you uploaded, and where each one got to.</p>
        </div>
        <Link to="/get-cash" className="btn btn-primary">
          <Icon name="upload" />
          Get cash for an invoice
        </Link>
      </div>
      <div className="tiles">
        <Tile label="Out with lenders" value={money(sum(by(["funded"])))} sub="Waiting for your buyers to pay" />
        <Tile label="Waiting for you" value={money(sum(by(["needs_you", "held"])))} sub="Held or above your ask-me limit" />
        <Tile label="Paid in full" value={money(sum(by(["paid"])))} sub="Settled through the vault" />
      </div>
      <section className="card">
        <div className="sec" style={{ flexWrap: "wrap" }}>
          <div className="filters" role="group" aria-label="Filter by status">
            {FILTERS.map((f, i) => (
              <button key={f.label} type="button" aria-pressed={i === filter} onClick={() => setFilter(i)}>
                {f.label} · {f.keys ? by(f.keys).length : state.cases.length}
              </button>
            ))}
          </div>
          <div style={{ flex: "0 1 280px", minWidth: 200 }}>
            <label htmlFor="q" className="sr">
              Search invoices
            </label>
            <input id="q" type="search" placeholder="Search by number or buyer" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
        {shown.length > 0 ? (
          <CaseTable cases={shown} />
        ) : (
          <p className="help" style={{ padding: "16px 0" }}>
            {state.cases.length === 0 ? "No invoices yet." : "No invoices match."}
          </p>
        )}
        <p className="help">
          "Held" means a check failed and a person has to look. "Declined" means your rule, the registry or the wallet refused it. In both
          cases nothing was signed and you were not charged.
        </p>
      </section>
    </>
  );
}
