// The orchestrator's responses, as the web app reads them. Field names and meanings follow
// shared/schemas.py (docs/00-scope.md section 4). Money and rates are decimal strings; scores are 0.0-1.0.

export type Decimal = string;

export interface Party {
  name: string;
  tax_id: string;
}

export interface LineItem {
  description: string;
  qty: Decimal;
  unit_price: Decimal;
  total: Decimal;
}

export interface Invoice {
  invoice_id: string;
  supplier: Party;
  buyer: Party;
  invoice_no: string;
  issue_date: string;
  due_date: string;
  amount: Decimal;
  currency: string;
  line_items: LineItem[];
  confidence: number;
  injection_flags: string[];
  fraud_score: number;
  fraud_flags: string[];
  doc_hash: string;
  invoice_fingerprint: string;
  // Sent by newer ocr-ai versions only.
  fraud_details?: { code: string; reason?: string }[];
  validation_flags?: string[];
}

export interface Decision {
  decision: "approve" | "review" | "reject";
  advance_rate: Decimal;
  limit: Decimal;
  fee_rate: Decimal; // per 30 days
  apr?: Decimal | null;
  risk_score: number;
  reasons: string[];
  model_version: string;
  policy_version: string;
  fee_amount?: Decimal;
  tenor_days?: number;
  decision_id?: string;
  valid_until?: string;
}

export interface Offer {
  lender: string;
  lender_id?: string;
  advance_rate: Decimal;
  apr: Decimal;
  within_mandate: boolean;
  chosen: boolean;
}

export type WalletStatus = "executed" | "blocked" | "pending_approval" | "failed";

export interface WalletResult {
  tx_id: string;
  status: WalletStatus;
  chain_ref?: string | null;
  approvals_required?: number;
  audit_ref?: string;
  chain?: string;
  explorer_url?: string | null;
  block_reason?: string | null;
}

/** POST /flow/run: every step that ran, and how the flow ended. */
export interface FlowResult {
  mandate_id?: string;
  ocr: Invoice;
  register?: WalletResult; // TX-1, the on-chain duplicate check
  registry?: { invoice_fingerprint: string; duplicate: boolean };
  policy?: Decision;
  approve?: WalletResult; // TX-2, the recorded credit approval
  offers?: Offer[];
  wallet?: WalletResult; // TX-4, the draw
  outcome: string;
}

/** POST /flow/attack/{case}, or a saved attack from ui/fixtures. */
export interface AttackResult {
  case: string;
  title: string;
  status: string;
  block_reason?: string | null;
  chain_ref?: string | null;
  wallet?: WalletResult;
}

export interface Mandate {
  mandate_id: string;
  max_ltv: Decimal;
  max_apr: Decimal;
  max_predicted_default: Decimal;
  max_amount_per_tx: Decimal;
  daily_cap: Decimal;
  human_review_above: Decimal;
  payee_allowlist: string[];
  valid_from: string;
  expires_at: string;
}
