// Pure derivations from the saved state: what each invoice's status is, how much money moved, and the
// activity feed. Everything is computed from the services' responses; nothing here decides anything.

import type { Settlement } from "./api";
import { blockWords, decidingReasons } from "./copy";
import { lesser, minus, money, percent as pct, plus, scorePercent as score, times } from "./money";
import type { AttackResult, FlowResult, Mandate } from "./types";

export interface Case {
  id: string;
  at: string; // when it was uploaded, ISO
  filename: string;
  flow: FlowResult;
  settlement?: Settlement;
  owner?: "approved" | "declined" | "closed"; // what the owner did on the Needs you page
}

export interface Protection {
  id: string;
  at: string;
  attack: AttackResult;
  saved: boolean; // a saved response stood in because the orchestrator has no live route for this case
}

export type Tone = "ok" | "hold" | "stop" | "grey" | "info";
export type StatusKey = "paid" | "funded" | "needs_you" | "held" | "declined" | "closed" | "stopped";

export interface Status {
  key: StatusKey;
  label: string;
  tone: Tone;
  why: string[];
}

export function status(c: Case): Status {
  const { flow } = c;
  const w = flow.wallet;
  if (c.settlement?.status === "executed") return { key: "paid", label: "Paid in full", tone: "grey", why: [] };
  if (w?.status === "executed") return { key: "funded", label: "Funded · waiting for buyer", tone: "ok", why: [] };
  if (w?.status === "pending_approval") {
    if (c.owner === "declined") return { key: "declined", label: "Declined by you", tone: "grey", why: [] };
    return { key: "needs_you", label: "Needs you", tone: "hold", why: [blockWords("NeedsHumanApproval")] };
  }
  if (w) return { key: "declined", label: "Declined", tone: "stop", why: [blockWords(w.block_reason)] };
  if (flow.register && flow.register.status !== "executed") {
    const label = flow.registry?.duplicate ? "Declined · already financed" : "Declined";
    return { key: "declined", label, tone: "stop", why: [blockWords(flow.register.block_reason)] };
  }
  const policy = flow.policy;
  if (policy?.decision === "review") {
    if (c.owner === "closed") return { key: "closed", label: "Closed by you", tone: "grey", why: [] };
    return { key: "held", label: "Held · needs a look", tone: "hold", why: decidingReasons(policy.reasons) };
  }
  if (policy?.decision === "reject") {
    return { key: "declined", label: "Declined", tone: "stop", why: decidingReasons(policy.reasons) };
  }
  return { key: "stopped", label: "Stopped", tone: "stop", why: [flow.outcome] };
}

/** What a draw pays now: the chosen lender's advance on the face value, never above the approved limit. */
export function advance(flow: FlowResult): bigint | null {
  const p = flow.policy;
  if (!p || p.decision !== "approve") return null;
  const chosen = flow.offers?.find((o) => o.chosen);
  return chosen ? lesser(p.limit, times(flow.ocr.amount, chosen.advance_rate)) : plus(p.limit);
}

export const fee = (flow: FlowResult): bigint | null => (flow.policy?.fee_amount ? plus(flow.policy.fee_amount) : null);

/** What reaches the owner when the buyer pays: face value less the advance already paid and the fee. */
export function onPayment(flow: FlowResult): bigint | null {
  const a = advance(flow);
  const f = fee(flow);
  return a === null || f === null ? null : minus(flow.ocr.amount, a, f);
}

export const chosenOffer = (flow: FlowResult) => flow.offers?.find((o) => o.chosen);

/** The rule checks an approved offer passed, each as [label, detail]. */
export function ruleChecks(flow: FlowResult, m: Mandate): [string, string][] {
  const p = flow.policy;
  if (!p || p.decision !== "approve") return [];
  const offer = chosenOffer(flow);
  const apr = offer?.apr ?? p.apr;
  const out: [string, string][] = [
    [`Advance ${pct(offer?.advance_rate ?? p.advance_rate)}`, `Your maximum is ${pct(m.max_ltv)}.`],
  ];
  if (apr) out.push([`Cost ${pct(apr)} a year`, `Your maximum is ${pct(m.max_apr)}.`]);
  out.push([`Buyer default risk ${score(p.risk_score)}`, `Your limit is ${pct(m.max_predicted_default)}.`]);
  // The wallet asks the owner when the draw itself reaches the limit (agent-wallet guard pipeline).
  const draw = advance(flow);
  if (draw !== null) {
    out.push(
      minus(draw, m.human_review_above) >= 0n
        ? ["Above your ask-me limit", `A draw of ${money(draw)} reaches your limit of ${money(m.human_review_above)}, so you approve it.`]
        : ["No approval needed", `A draw of ${money(draw)} is under your ask-me limit of ${money(m.human_review_above)}.`],
    );
  }
  out.push(["Paid only to you", "Your verified account, nowhere else, whatever the invoice says."]);
  return out;
}

export interface Totals {
  received: bigint;
  coming: bigint;
  fees: bigint;
  blocked: number;
  needsYou: number;
}

export function totals(cases: Case[], protections: Protection[]): Totals {
  const t: Totals = { received: 0n, coming: 0n, fees: 0n, blocked: 0, needsYou: 0 };
  for (const c of cases) {
    const s = status(c).key;
    if (s === "funded" || s === "paid") {
      t.received += advance(c.flow) ?? 0n;
      t.fees += fee(c.flow) ?? 0n;
      if (s === "funded") t.coming += onPayment(c.flow) ?? 0n;
      else t.received += onPayment(c.flow) ?? 0n;
    }
    if (s === "declined" && status(c).tone === "stop") t.blocked += 1;
    if (s === "needs_you" || s === "held") t.needsYou += 1;
  }
  t.blocked += protections.filter((p) => p.attack.status === "blocked").length;
  return t;
}

export interface Event {
  id: string;
  at: string;
  tone: "ok" | "bad" | "info" | "warn";
  title: string;
  detail: string;
  amount?: bigint;
  receipt?: string | null;
  money: boolean; // moved, or will move, money
}

const ATTACK_TITLES: Record<string, string> = {
  A1: "a payment to an account that is not yours",
  A2: "the same invoice financed twice",
  A3: "a lender quote at 19% a year",
  A4: "a draw above the approved amount",
  A5: "financing with an expired business verification",
  A6: "the agent acting after your rule expired",
};

export const attackTitle = (a: AttackResult): string => ATTACK_TITLES[a.case] ?? a.title;

/** Newest first. */
export function activity(cases: Case[], protections: Protection[]): Event[] {
  const out: Event[] = [];
  for (const c of cases) {
    const { flow } = c;
    const no = flow.ocr.invoice_no;
    const add = (e: Omit<Event, "id" | "at" | "money"> & { money?: boolean }) =>
      out.push({ money: false, ...e, id: `${c.id}:${out.length}`, at: c.at });
    if (flow.register?.status === "executed") {
      add({ tone: "ok", title: "Invoice registered", detail: `${no} · recorded so it cannot be financed twice`, receipt: flow.register.chain_ref });
    } else if (flow.register) {
      add({ tone: "bad", title: "Blocked: same invoice uploaded twice", detail: `${no} · ${blockWords(flow.register.block_reason)}`, receipt: flow.register.chain_ref });
    }
    const p = flow.policy;
    if (p?.decision === "review") {
      add({ tone: "warn", title: `Held: ${no}`, detail: decidingReasons(p.reasons).join(". ") || "A person needs to look" });
    } else if (p?.decision === "reject") {
      add({ tone: "bad", title: `Declined: ${no}`, detail: decidingReasons(p.reasons).join(". ") });
    }
    if (flow.approve?.status === "executed" && p) {
      add({ tone: "ok", title: "Credit approved", detail: `${no} · up to ${money(p.limit)}, inside your rule`, receipt: flow.approve.chain_ref });
    }
    const w = flow.wallet;
    if (w?.status === "executed") {
      const lender = chosenOffer(flow)?.lender;
      add({ tone: "ok", title: "Advance received", detail: `${no}${lender ? ` · ${lender}` : ""} · to your verified account`, amount: advance(flow) ?? undefined, receipt: w.chain_ref, money: true });
      const f = fee(flow);
      if (f !== null) add({ tone: "info", title: "Fee reserved", detail: "Paid from the buyer's payment, not from you now", amount: f, money: true });
    } else if (w?.status === "pending_approval") {
      add({ tone: "warn", title: `Waiting for your approval: ${no}`, detail: blockWords("NeedsHumanApproval") });
    } else if (w) {
      add({ tone: "bad", title: `Blocked: ${no}`, detail: blockWords(w.block_reason), receipt: w.chain_ref });
    }
    if (c.settlement?.status === "executed") {
      add({ tone: "ok", title: `${flow.ocr.buyer.name} paid`, detail: "The lender was repaid with the fee; the rest came to you", amount: onPayment(flow) ?? undefined, receipt: c.settlement.chain_ref, money: true });
    }
  }
  for (const p of protections) {
    const a = p.attack;
    const held = a.status === "blocked";
    out.push({
      id: p.id,
      at: p.at,
      tone: held ? "bad" : "warn",
      title: `${held ? "Blocked" : "Not stopped"}: ${attackTitle(a)}`,
      detail: held ? `${blockWords(a.block_reason)}. You were not charged.` : `The wallet answered ${a.status}.`,
      receipt: a.chain_ref ?? a.wallet?.chain_ref,
      money: false,
    });
  }
  // Stable: newest first, and within one upload the later step first.
  return out.map((e, i) => ({ e, i })).sort((x, y) => y.e.at.localeCompare(x.e.at) || y.i - x.i).map(({ e }) => e);
}

/** One CSV row per event. Cells that a spreadsheet would run as a formula are quoted as text. */
export function activityCsv(events: Event[]): string {
  const cell = (v: string) => {
    const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  const rows = events.map((e) =>
    [e.at, e.title, e.detail, e.amount === undefined ? "" : money(e.amount), e.receipt ?? ""].map(cell).join(","),
  );
  return [["when", "what", "detail", "amount", "receipt"].map(cell).join(","), ...rows].join("\n");
}
