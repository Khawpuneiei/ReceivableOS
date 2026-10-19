// The pieces every invoice page shares: how we checked it, what we read, and the ledger receipts.

import { blockWords, decidingReasons, findings } from "../copy";
import { advance } from "../model";
import { daysBetween, day, grouped, money, percent, scorePercent } from "../money";
import type { FlowResult } from "../types";
import { Icon, type IconName } from "./Icon";
import { Kv } from "./ui";

type CheckState = "pass" | "fail" | "warn" | "skip" | "wait";
interface Check {
  state: CheckState;
  title: string;
  detail: string;
}

const MIN_CONFIDENCE = 0.8;
const MAX_FRAUD = 0.3;
const ICON: Record<CheckState, IconName> = { pass: "check", fail: "cross", warn: "alert", skip: "next", wait: "clock" };

export const PENDING_CHECKS = [
  "Reading the invoice",
  "Looking for hidden instructions",
  "Checking for tampering",
  "Making sure it is not already financed",
  "Checking the buyer and comparing lender quotes",
];

export function checksFor(flow: FlowResult): Check[] {
  const inv = flow.ocr;
  const out: Check[] = [];
  const conf = scorePercent(inv.confidence);
  out.push(
    inv.confidence >= MIN_CONFIDENCE
      ? { state: "pass", title: "Read the invoice", detail: `${conf} confident. Supplier, buyer, amounts and dates found.` }
      : { state: "warn", title: "Could not read it clearly enough", detail: `${conf} confident; we need 80% to go on without a person.` },
  );
  out.push(
    inv.injection_flags.length === 0
      ? { state: "pass", title: "Looked for hidden instructions", detail: "None found. Text inside a document is never treated as an instruction." }
      : { state: "fail", title: "Found hidden instructions", detail: "The file carries text aimed at our AI. It was ignored, and the invoice was held for a person." },
  );
  const found = findings(inv).filter((f) => !f.includes("hidden instructions"));
  out.push(
    inv.fraud_score < MAX_FRAUD
      ? { state: "pass", title: "Checked for tampering", detail: `Low risk: ${inv.fraud_score.toFixed(2)} on a scale where 0.30 stops the process.` }
      : { state: "fail", title: "Signs of tampering", detail: `Risk ${inv.fraud_score.toFixed(2)}, at or above 0.30${found.length ? `: ${found.join("; ")}` : ""}.` },
  );
  if (!flow.register) out.push({ state: "skip", title: "Duplicate check not reached", detail: "The process stopped before this step." });
  else if (flow.register.status !== "executed") {
    out.push({ state: "fail", title: "Already financed", detail: `${blockWords(flow.register.block_reason)}.` });
  } else out.push({ state: "pass", title: "Made sure it is not already financed", detail: "First time this invoice is seen, even if the PDF were re-saved." });
  const p = flow.policy;
  if (!p) out.push({ state: "skip", title: "Buyer and price not checked", detail: "The process stopped before this step." });
  else if (p.decision === "approve") {
    const n = flow.offers?.length ?? 0;
    out.push({ state: "pass", title: `Checked the buyer${n ? ` and compared ${n} lender quotes` : ""}`, detail: `${flow.ocr.buyer.name}: ${scorePercent(p.risk_score)} chance of not paying.` });
  } else {
    const why = decidingReasons(p.reasons).join(". ");
    out.push({ state: p.decision === "review" ? "warn" : "fail", title: p.decision === "review" ? "Sent to a person" : "Declined", detail: `${why || "See the reasons above"}.` });
  }
  const w = flow.wallet;
  if (w?.status === "executed") {
    const a = advance(flow);
    out.push({ state: "pass", title: "Paid to your verified account", detail: a === null ? "The wallet's guard approved the payment." : `${money(a)}, after the wallet's guard re-checked your rule.` });
  } else if (w?.status === "pending_approval") {
    out.push({ state: "warn", title: "Waiting for your approval", detail: `${blockWords("NeedsHumanApproval")}.` });
  } else if (w) out.push({ state: "fail", title: "Payment refused by the wallet", detail: `${blockWords(w.block_reason)}.` });
  return out;
}

export function Checks({ flow, running }: { flow?: FlowResult; running?: boolean }) {
  const rows: Check[] = flow
    ? checksFor(flow)
    : PENDING_CHECKS.map((title) => ({ state: "wait" as const, title, detail: running ? "Working on it" : "Not started" }));
  return (
    <ul className="checks" aria-busy={running || undefined}>
      {rows.map((c) => (
        <li key={c.title} className={`check ${c.state}`}>
          {running ? <span className="spin" aria-hidden="true" /> : <Icon name={ICON[c.state]} />}
          <span>
            <b>{c.title}</b>
            <div>{c.detail}</div>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Facts({ flow }: { flow: FlowResult }) {
  const inv = flow.ocr;
  return (
    <div>
      <Kv k="Invoice" v={<span className="mono">{inv.invoice_no}</span>} />
      <Kv k="Buyer" v={<span className="wrap">{inv.buyer.name}</span>} />
      <Kv k="Buyer tax ID" v={<span className="mono">{inv.buyer.tax_id}</span>} />
      <Kv k="Total" v={money(inv.amount, inv.currency)} />
      <Kv k="Issued" v={day(inv.issue_date)} />
      <Kv k="Due" v={`${day(inv.due_date)} · ${daysBetween(inv.issue_date, inv.due_date)} days`} />
      {inv.line_items.map((li, i) => (
        <Kv
          key={`${li.description}-${i}`}
          k={i === 0 ? "Lines" : ""}
          v={
            <span className="wrap">
              {li.description}
              <small className="help" style={{ display: "block", fontWeight: 400 }}>
                {grouped(li.qty)} × {grouped(li.unit_price)} = {grouped(li.total)}
              </small>
            </span>
          }
        />
      ))}
    </div>
  );
}

/** "mock:0x37b2...b872" -> "0x37b2…b872". */
export const shortRef = (ref?: string | null): string => {
  if (!ref) return "";
  const hex = ref.replace(/^[a-z]+:/, "");
  return hex.length > 14 ? `${hex.slice(0, 6)}…${hex.slice(-4)}` : hex;
};

export function Receipts({ flow, settled }: { flow: FlowResult; settled?: { chain_ref?: string | null; status: string } }) {
  const label = (done: string, refused: string, st?: string) => (st === "executed" ? done : refused);
  const rows: [string, string | null | undefined][] = [
    [label("Invoice registered", "Registration refused", flow.register?.status), flow.register?.chain_ref],
    [label("Credit approved", "Approval refused", flow.approve?.status), flow.approve?.chain_ref],
    [label("Advance paid", "Payment refused", flow.wallet?.status), flow.wallet?.chain_ref],
    [label("Buyer payment settled", "Settlement refused", settled?.status), settled?.chain_ref],
  ];
  const shown = rows.filter(([, ref]) => ref);
  const chain = flow.wallet?.chain ?? flow.register?.chain;
  return (
    <div>
      {shown.length === 0 && <p className="help">No ledger records: the process stopped before anything was written.</p>}
      {shown.map(([name, ref]) => (
        <Kv key={name} k={name} v={<span className="mono" title={ref ?? ""}>{shortRef(ref)}</span>} />
      ))}
      {chain === "mock" && <p className="help">Demo ledger. Live, the same records sit on FISCO BCOS.</p>}
      <p className="help">Each record holds fingerprints and amounts, never the invoice itself or your business details.</p>
    </div>
  );
}

export const advanceRate = (flow: FlowResult): string | null =>
  flow.offers?.find((o) => o.chosen)?.advance_rate ?? flow.policy?.advance_rate ?? null;

export const ratePct = (r?: string | null) => (r ? percent(r) : "-");
