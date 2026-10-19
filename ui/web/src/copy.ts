// What the services decided, in words an SME owner reads without the docs. Nothing here decides anything:
// every sentence comes from a code in a response. Unknown codes fall back to the service's own text.

import type { Invoice } from "./types";

const REASONS: Record<string, string> = {
  "HARD.INJECTION": "The file contains text that tries to give our AI instructions",
  "HARD.FRAUD_SCORE": "Our checks found signs the invoice was altered",
  "HARD.LOW_CONFIDENCE": "We could not read the invoice clearly enough",
  "HARD.KYC_UNKNOWN": "Your business verification is missing",
  "REVIEW.FRAUD_FLAGS": "Our checks raised a flag on this invoice",
  "REVIEW.LINE_ITEMS_MISMATCH": "The line items do not add up to the total",
  "REVIEW.PD_ABOVE_CAP": "The buyer's risk of not paying is above your limit",
  "REVIEW.LARGE_TICKET": "The amount is large enough to need a person",
  "REVIEW.NEW_SUPPLIER": "Your business is new to us",
  "REVIEW.THIN_PROFILE": "There is too little payment history yet",
  "REVIEW.UNCONFIRMED_BUYER": "The buyer has not confirmed this invoice",
  "REVIEW.CONCENTRATION": "Too much of your financing is with this one buyer",
  "REVIEW.MANDATE_APR": "The price would break your cost limit",
  "KO.DUPLICATE": "This invoice was already financed",
  "KO.KYC_INVALID": "Your business verification has expired",
  "KO.PD_TOO_HIGH": "The buyer is too likely not to pay",
  "KO.OVERDUE": "The invoice is already overdue",
  "KO.TOO_OLD": "The invoice is too old to finance",
  "KO.TENOR_TOO_SHORT": "The invoice is due too soon to finance",
  "KO.TENOR_TOO_LONG": "The invoice is due too far away to finance",
  "KO.DATES_INVALID": "The invoice dates do not make sense",
  "KO.CURRENCY": "The currency is not one we finance",
  "KO.PRICING": "No price fits inside your rule",
};

const BLOCKS: Record<string, string> = {
  DuplicateReceivable: "This invoice was already financed, so it cannot be financed twice",
  NotApproved: "There was no credit approval behind the payment, so the wallet refused it",
  PayeeNotAllowed: "The payment named an account that is not yours, so the wallet refused it",
  AprAboveMandate: "A lender quote cost more than your yearly limit, so it was refused",
  AdvanceAboveMandate: "The advance was above your maximum, so it was refused",
  AmountAboveLimit: "The draw was larger than the approved amount, so it was refused",
  AmountAboveTxCap: "The draw was above the per-transaction cap",
  DailyCapExceeded: "The draw would have passed the daily cap",
  PdAboveMandate: "The buyer's risk of not paying is above your limit",
  MandateExpired: "Your rule had expired, so the agent could not act",
  MandateNotYetValid: "Your rule was not active yet",
  KycNotVerified: "Your business verification is not confirmed",
  CurrencyNotAllowed: "The currency is not allowed by your rule",
  HoldExpired: "The approval expired before the money was drawn",
  NeedsHumanApproval: "The amount is above your ask-me limit",
  ApprovalPending: "The payment is waiting for you to approve it",
  ApprovalDeclined: "You declined the payment",
  NoMandate: "You have no active rule, so the agent cannot act",
};

const FINDINGS: Record<string, string> = {
  duplicate_fingerprint: "the same invoice was seen before",
  duplicate_invoice_hash: "this exact file was seen before",
  near_duplicate: "a very similar invoice was seen before",
  math_inconsistent: "the line items do not add up to the total",
  bank_account_changed: "the bank account on the invoice changed",
  pdf_text_covered: "text in the PDF is covered by something drawn on top",
  pdf_appended_text_layer: "text was added to the PDF after it was made",
  pdf_incremental_update: "the PDF was edited after it was saved",
  qr_payee_mismatch: "the payment QR pays someone other than you",
  qr_amount_mismatch: "the payment QR asks for a different amount",
  amount_outlier: "the amount is far above what you usually bill this buyer",
};

/** "HARD.INJECTION: details (x)" -> owner words, or the service's own text when the code is unknown. */
export function reasonWords(reason: string): string {
  const [code, ...rest] = reason.split(":");
  const known = REASONS[code.trim()];
  if (known) return known;
  return (rest.join(":").trim() || reason).replace(/\s*\([^)]*\)\s*$/, "");
}

export const blockWords = (code?: string | null): string =>
  (code && BLOCKS[code]) || (code ? `Refused by the wallet (${code})` : "Refused by the wallet");

/** Policy reasons that sent the invoice to review or rejected it, in owner words. */
export const decidingReasons = (reasons: string[]): string[] =>
  reasons.filter((r) => /^(HARD|KO|REVIEW)\./.test(r)).map(reasonWords);

/** What the document checks found, one line each. */
export function findings(inv: Invoice): string[] {
  const out = new Set<string>();
  for (const d of inv.fraud_details ?? []) out.add(FINDINGS[d.code] ?? d.reason ?? d.code.replace(/_/g, " "));
  for (const code of inv.fraud_flags) out.add(FINDINGS[code] ?? code.replace(/_/g, " "));
  if (inv.injection_flags.length) out.add("the file carries hidden instructions aimed at our AI");
  return [...out];
}
