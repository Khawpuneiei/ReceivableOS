// The only way the app talks to the backend. Live mode calls the orchestrator through /api (the dev and
// preview servers forward it and add the caller token); fixture mode replays responses recorded from the
// live stack in ui/fixtures, so the app works with no backend at all.

import a1 from "../../fixtures/a1.json";
import a2 from "../../fixtures/a2.json";
import a3 from "../../fixtures/a3.json";
import a4 from "../../fixtures/a4.json";
import a5 from "../../fixtures/a5.json";
import a6 from "../../fixtures/a6.json";
import saved from "../../fixtures/happy.json";
import duplicateRun from "../../fixtures/runs/duplicate.json";
import happyRun from "../../fixtures/runs/happy.json";
import inflatedRun from "../../fixtures/runs/inflated.json";
import injectedRun from "../../fixtures/runs/injected.json";
import happyPdf from "../../../data/invoices/demo/01_happy.pdf?url";
import injectedPdf from "../../../data/invoices/demo/02_injected.pdf?url";
import inflatedPdf from "../../../data/invoices/demo/03_inflated.pdf?url";
import duplicatePdf from "../../../data/invoices/demo/04_duplicate.pdf?url";
import type { AttackResult, FlowResult, Mandate, WalletResult } from "./types";

export type Mode = "live" | "fixtures";

export interface Settlement {
  invoice_id?: string;
  amount_paid?: string;
  status: string;
  tx_id?: string;
  chain_ref?: string | null;
  block_reason?: string | null;
}

export interface Api {
  mode: Mode;
  runFlow(file: Blob, filename: string, mandateId: string): Promise<FlowResult>;
  repay(invoiceId: string): Promise<Settlement>;
  attack(caseId: string): Promise<AttackResult>;
  compileMandate(text: string): Promise<{ mandate?: Mandate }>;
  confirm(txId: string): Promise<WalletResult>;
}

/** kind: "unavailable" (no answer), "unsupported" (the orchestrator has no such route yet), "refused". */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: "unavailable" | "unsupported" | "refused",
  ) {
    super(message);
  }
}

const clone = <T>(x: unknown): T => structuredClone(x) as T;

export interface Sample {
  id: "happy" | "injected" | "inflated" | "duplicate";
  label: string;
  hint: string;
  filename: string;
  url: string;
  run: FlowResult;
}

export const SAMPLES: Sample[] = [
  {
    id: "happy",
    label: "A clean invoice",
    hint: "SFP-INV-2026-0142, THB 749,000.00 to Mekong Basket Retail",
    filename: "01_happy.pdf",
    url: happyPdf,
    run: clone(happyRun),
  },
  {
    id: "injected",
    label: "An invoice with hidden instructions",
    hint: "Text inside the file tries to make our AI approve it",
    filename: "02_injected.pdf",
    url: injectedPdf,
    run: clone(injectedRun),
  },
  {
    id: "inflated",
    label: "An invoice with altered totals",
    hint: "The lines do not add up to the amount asked",
    filename: "03_inflated.pdf",
    url: inflatedPdf,
    run: clone(inflatedRun),
  },
  {
    id: "duplicate",
    label: "A re-saved copy of the clean invoice",
    hint: "Same invoice, new PDF file",
    filename: "04_duplicate.pdf",
    url: duplicatePdf,
    run: clone(duplicateRun),
  },
];

export const SAVED_MANDATE = clone<Mandate>(saved.mandate.mandate);
export const SAVED_RULE_TEXT: string = saved.mandate_text;
const SAVED_ATTACKS: Record<string, AttackResult> = { A1: a1, A2: a2, A3: a3, A4: a4, A5: a5, A6: a6 };
export const ATTACK_CASES = Object.keys(SAVED_ATTACKS);
export const savedAttack = (caseId: string): AttackResult => clone(SAVED_ATTACKS[caseId]);

/** Which saved run a file stands for in fixture mode: by demo file name, else the clean invoice. */
export function sampleFor(filename: string): Sample {
  const name = filename.toLowerCase();
  const byName = SAMPLES.find((s) => s.filename === name);
  if (byName) return byName;
  const byWord = SAMPLES.find((s) => s.id !== "happy" && name.includes(s.id.slice(0, 5)));
  return byWord ?? SAMPLES[0];
}

const SERVICES: [string, string][] = [
  ["/ocr/", "the invoice reader"],
  ["/policy/", "the credit check"],
  ["/wallet/", "the wallet"],
];

/** 'http://x:8001/ocr/extract answered 415: {"detail": "..."}' -> 'the invoice reader refused the file: ...' */
export function plainError(detail: string): string {
  const service = SERVICES.find(([key]) => detail.includes(key))?.[1] ?? "a service";
  const m = /answered (\d{3}): ?([\s\S]*)/.exec(detail);
  if (!m) return `${service} failed: ${detail.slice(0, 200)}`;
  let reason = m[2];
  try {
    const inner = JSON.parse(reason).detail;
    if (typeof inner === "string") reason = inner;
  } catch {
    // the service's body was cut short or is not JSON: show it as text
  }
  return `${service} ${m[1].startsWith("4") ? "refused the request" : "failed"}: ${reason.slice(0, 200)}`;
}

export function liveApi(base = "/api"): Api {
  async function call<T>(path: string, init: RequestInit): Promise<T> {
    let r: Response;
    try {
      r = await fetch(`${base}${path}`, init);
    } catch {
      throw new ApiError("We could not reach ReceivableOS. Check that the orchestrator is running.", "unavailable");
    }
    if (r.status === 404 || r.status === 405) throw new ApiError(`${path} is not served yet`, "unsupported");
    if (r.status === 401 || r.status === 403) {
      throw new ApiError("The orchestrator refused the app: set ORCHESTRATOR_TOKEN for the web server.", "refused");
    }
    if (!r.ok) {
      const detail = await r
        .json()
        .then((b) => (typeof b?.detail === "string" ? b.detail : ""))
        .catch(() => "");
      const message = detail ? plainError(detail) : `ReceivableOS answered with an error (HTTP ${r.status})`;
      throw new ApiError(message, r.status >= 500 ? "unavailable" : "refused");
    }
    return (await r.json()) as T;
  }
  const form = (fields: Record<string, string | [Blob, string]>): FormData => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) {
      if (typeof v === "string") fd.append(k, v);
      else fd.append(k, v[0], v[1]);
    }
    return fd;
  };
  return {
    mode: "live",
    runFlow: (file, filename, mandateId) =>
      call("/flow/run", { method: "POST", body: form({ file: [file, filename], mandate_id: mandateId }) }),
    repay: (invoiceId) => call("/flow/repay", { method: "POST", body: form({ invoice_id: invoiceId }) }),
    attack: (caseId) => call(`/flow/attack/${encodeURIComponent(caseId)}`, { method: "POST" }),
    compileMandate: (text) =>
      call("/flow/mandate/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }),
    confirm: (txId) => call(`/flow/confirm/${encodeURIComponent(txId)}`, { method: "POST" }),
  };
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function fixtureApi(delayMs = 700): Api {
  const funded = new Set<string>();
  const unsupported = (what: string) => Promise.reject(new ApiError(`${what} is not available in sample mode`, "unsupported"));
  return {
    mode: "fixtures",
    async runFlow(_file, filename) {
      await pause(delayMs);
      let sample = sampleFor(filename);
      // The registry refuses an invoice it already financed; the saved duplicate run is that refusal.
      if (sample.id === "happy" && funded.has(sample.run.ocr.invoice_fingerprint)) sample = SAMPLES[3];
      const run = clone<FlowResult>(sample.run);
      if (run.wallet?.status === "executed") funded.add(run.ocr.invoice_fingerprint);
      return run;
    },
    async repay(invoiceId) {
      await pause(delayMs);
      return { invoice_id: invoiceId, ...clone<Settlement>(saved.repay) };
    },
    async attack(caseId) {
      await pause(delayMs / 4);
      return savedAttack(caseId);
    },
    compileMandate: () => unsupported("Saving a rule to the orchestrator"),
    confirm: () => unsupported("Approving a payment"),
  };
}

export const defaultApi = (): Api => (__UI_MODE__ === "live" ? liveApi() : fixtureApi());
