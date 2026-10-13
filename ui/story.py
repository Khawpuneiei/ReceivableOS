"""The flow as a judge reads it: six steps with a state each, and one plain-language verdict.

Pure functions over the view model (no Streamlit import), so they are unit-tested directly. Every sentence is
built from fields already in the response; nothing here decides anything, it only explains what the services
decided. Step states use the screen's colours: done (green), review (amber), stopped (red), skipped (grey).
"""

from __future__ import annotations

import format as fmt

DONE, REVIEW, STOPPED, SKIPPED, WAITING = "done", "review", "stopped", "skipped", "waiting"
STATE_COLOUR = {
    DONE: fmt.GREEN,
    REVIEW: fmt.AMBER,
    STOPPED: fmt.RED,
    SKIPPED: fmt.GREY,
    WAITING: fmt.GREY,
}
STATE_ICON = {DONE: "✓", REVIEW: "!", STOPPED: "✕", SKIPPED: "–", WAITING: "…"}

# Policy reason codes and wallet block reasons, in words a judge reads without the docs.
PLAIN = {
    "HARD.INJECTION": "the document contains text that tries to give the AI instructions",
    "HARD.FRAUD_SCORE": "the fraud checks scored the invoice too risky",
    "HARD.LOW_CONFIDENCE": "the invoice could not be read confidently enough",
    "HARD.KYC_UNKNOWN": "the supplier's identity check is missing",
    "REVIEW.FRAUD_FLAGS": "the fraud checks raised a flag",
    "REVIEW.LINE_ITEMS_MISMATCH": "the line items do not add up to the invoice total",
    "REVIEW.PD_ABOVE_CAP": "the buyer's predicted default is above the SME's limit",
    "REVIEW.LARGE_TICKET": "the amount is large enough to need a person",
    "REVIEW.NEW_SUPPLIER": "the supplier is new",
    "REVIEW.THIN_PROFILE": "there is too little history on the parties",
    "REVIEW.UNCONFIRMED_BUYER": "the buyer has not confirmed the invoice",
    "REVIEW.CONCENTRATION": "too much exposure to one buyer",
    "REVIEW.MANDATE_APR": "the price would break the SME's APR limit",
    "KO.DUPLICATE": "this invoice was already financed",
    "KO.KYC_INVALID": "the supplier's identity check is not valid",
    "KO.PD_TOO_HIGH": "the buyer is too likely to default",
    "KO.OVERDUE": "the invoice is already overdue",
    "KO.TOO_OLD": "the invoice is too old",
    "KO.DATES_INVALID": "the invoice dates do not make sense",
    "KO.CURRENCY": "the currency is not allowed",
    "KO.PRICING": "no price fits inside the SME's limits",
    "DuplicateReceivable": "the on-chain registry already holds this invoice, so it cannot be financed twice",
    "NotApproved": "there is no recorded credit approval for this invoice, so the wallet refuses to pay",
    "PayeeNotAllowed": "the payee is not on the SME's allowlist",
    "AprAboveMandate": "the lender's APR is above the SME's ceiling",
    "AdvanceAboveMandate": "the advance is above the SME's maximum",
    "AmountAboveLimit": "the draw is larger than the approved limit",
    "AmountAboveTxCap": "the draw is above the per-transaction cap",
    "DailyCapExceeded": "the draw would pass the daily cap",
    "PdAboveMandate": "the buyer's default risk is above the SME's limit",
    "MandateExpired": "the SME's mandate has expired",
    "MandateNotYetValid": "the SME's mandate is not active yet",
    "KycNotVerified": "the supplier's identity check is not verified",
    "CurrencyNotAllowed": "the currency is not allowed by the mandate",
    "HoldExpired": "the approval expired before the draw",
    # Newer agent-wallet guards (tripwire, agent firewall, session keys, signed decisions, human confirm).
    "HoneytokenTouched": "the request touched a decoy payee planted to catch attackers, so the wallet paused",
    "InvoiceQuarantined": "the invoice was quarantined after an earlier attack until an approver releases it",
    "InjectionSuspected": "the agent saw text that tries to give it instructions and stopped",
    "CanaryLeak": "a secret canary word leaked into the agent's output, a sign of prompt injection",
    "ToolArgNotAllowed": "the agent tried to add an argument it is not allowed to set",
    "AgentMisaligned": "the agent picked a different lender than the rules did on the same numbers",
    "NoQuoteInsideMandate": "no lender quote fits inside the SME's limits",
    "NotRegistered": "the invoice was never registered on chain",
    "SessionRevoked": "the agent's session key was revoked",
    "SessionExpired": "the agent's session key has expired",
    "SessionMandateChanged": "the SME changed its mandate after the agent's session key was issued",
    "SessionActionNotAllowed": "the agent's session key does not allow this action",
    "SessionInvoiceNotAllowed": "the agent's session key does not cover this invoice",
    "SessionTxCapExceeded": "the draw is above the agent's per-draw cap",
    "SessionBudgetExceeded": "the draw would take the agent over its budget",
    "DecisionUnsigned": "the credit decision carries no signature",
    "DecisionSignatureInvalid": "the credit decision's signature does not verify",
    "DecisionSignerUnknown": "the credit decision was signed by an unknown key",
    "DecisionTampered": "the credit decision was changed after it was signed",
    "NeedsHumanApproval": "the amount is large enough that a person must confirm it",
    "ApprovalDeclined": "a person declined the payment",
    "ApprovalExpired": "the person's approval window ran out",
    "SchemaInvalid": "the request was malformed and refused before any check",
}


# OCR fraud codes (fraud_flags / fraud_details[].code), including the tamper and QR checks in newer ocr-ai.
FINDING_PLAIN = {
    "duplicate_fingerprint": "the same invoice was seen before",
    "duplicate_invoice_hash": "this exact file was seen before",
    "near_duplicate": "a very similar invoice was seen before",
    "math_inconsistent": "the line items do not add up to the total",
    "bank_account_changed": "the supplier's bank account changed",
    "shared_bank_token": "the bank account is shared with other suppliers",
    "suspicious_cluster": "the invoice sits in a suspicious cluster",
    "po_amount_mismatch": "the amount differs from the purchase order",
    "po_currency_mismatch": "the currency differs from the purchase order",
    "po_party_mismatch": "the parties differ from the purchase order",
    "pdf_text_covered": "text in the PDF is covered by something drawn on top",
    "pdf_appended_text_layer": "text was added to the PDF after it was made",
    "pdf_font_anomaly": "part of the text uses a different font",
    "pdf_incremental_update": "the PDF was edited after it was saved",
    "qr_payee_mismatch": "the payment QR pays someone other than the supplier",
    "qr_amount_mismatch": "the payment QR asks for a different amount",
    "qr_crc_invalid": "the payment QR is corrupted",
    "qr_payee_unverified": "the payment QR's payee could not be checked",
    "amount_outlier": "the amount is at least 3x what this supplier usually bills this buyer",
}
INJECTION_CATEGORY = {
    "role_override": "tries to take over the AI's role",
    "decision_coercion": "tries to force an approval",
    "payee_redirect": "tries to redirect the payment",
    "score_tampering": "tries to zero the risk score",
    "addressed_command": "gives the AI a direct order",
    "tool_invocation": "tries to make the AI call a tool",
    "exfiltration": "tries to make the AI leak data",
}
# OCR validation_flags (newer ocr-ai): checks that the invoice agrees with itself.
VALIDATION_PLAIN = {
    "AMOUNT_WORDS_MISMATCH": "the total written in words does not match the digits",
    "DUE_DATE_TERMS_MISMATCH": "the due date does not match the invoice's own payment terms",
}
INJECTION_TECHNIQUE = {
    "plain": "plain",
    "normalized": "disguised",
    "homoglyph": "look-alike-letter",
    "leetspeak": "number-for-letter",
    "spacing": "spaced-out",
    "encoded": "encoded",
}


def findings(inv: dict) -> list[dict]:
    """What the document checks found, in words: [{kind, headline, detail, weight}].

    Reads fraud_details and injection_details when ocr-ai sends them (newer versions) and falls back to the
    bare flags otherwise, so an older ocr-ai still gets one row per flag. The detail text is ocr-ai's own.
    """
    out: list[dict] = []
    details = inv.get("fraud_details") or []
    seen = set()
    for d in details:
        code = str(d.get("code", ""))
        seen.add(code)
        out.append(
            {
                "kind": "fraud",
                "headline": FINDING_PLAIN.get(code, code.replace("_", " ")),
                "detail": d.get("reason"),
                "weight": d.get("weight"),
            }
        )
    for code in inv.get("fraud_flags", []):
        if code not in seen:
            out.append({"kind": "fraud", "headline": FINDING_PLAIN.get(code, code.replace("_", " "))})
    for code in inv.get("validation_flags") or []:
        words = VALIDATION_PLAIN.get(code, str(code).replace("_", " ").lower())
        out.append({"kind": "fraud", "headline": words})
    injections = inv.get("injection_details") or []
    for i in injections:
        what = INJECTION_CATEGORY.get(i.get("category"), str(i.get("category", "")).replace("_", " "))
        how = INJECTION_TECHNIQUE.get(i.get("technique"), i.get("technique"))
        where = str(i.get("channel") or "document").replace("_", " ")
        out.append(
            {
                "kind": "injection",
                "headline": f"hidden instructions for the AI: {what}",
                "detail": f"{how} text in the {where}" if how else None,
            }
        )
    if not injections:
        for flag in inv.get("injection_flags", []):
            out.append(
                {"kind": "injection", "headline": f"instructions for the AI found in the document ({flag})"}
            )
    return out


def plain(code: str | None) -> str | None:
    """'HARD.INJECTION' or 'HARD.INJECTION: details' -> plain words; None when the code is unknown."""
    if not code:
        return None
    return PLAIN.get(code.split(":", 1)[0].strip())


def _why(reasons: list[str], prefixes: tuple[str, ...]) -> list[str]:
    """Plain words for the reasons that start with one of `prefixes`, in order, without repeats."""
    out: list[str] = []
    for reason in reasons:
        words = plain(reason) if reason.startswith(prefixes) else None
        if words and words not in out:
            out.append(words)
    return out


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def steps(view: dict, paid: bool = False) -> list[dict]:
    """[{name, state, detail}] for Upload, Read, Registry, Policy, Wallet, Settle."""
    inv, policy = view.get("ocr") or {}, view.get("policy")
    wallet = view.get("wallet") or {}
    timeline = {t["step"]: t for t in view.get("timeline", [])}
    flags = len(inv.get("injection_flags", [])) + len(inv.get("fraud_flags", []))
    out = [
        {"name": "Upload", "state": DONE, "detail": f"invoice {inv.get('invoice_no', '-')}"},
        {
            "name": "Read (OCR)",
            "state": REVIEW if flags or float(inv.get("confidence", 1)) < 0.8 else DONE,
            "detail": f"{fmt.pct(inv.get('confidence'), 0)} confident · "
            + (f"{flags} warning flag(s)" if flags else "no warning flags"),
        },
    ]
    reg = timeline.get("TX-1")
    if (view.get("registry") or {}).get("duplicate") or (reg and reg["status"] == "blocked"):
        out.append({"name": "Registry", "state": STOPPED, "detail": "already financed: duplicate blocked"})
    else:
        out.append({"name": "Registry", "state": DONE, "detail": "new invoice, registered (TX-1)"})
    if not policy:
        out.append({"name": "Policy", "state": SKIPPED, "detail": "not reached"})
    else:
        decision = policy["decision"]
        state = {"approve": DONE, "review": REVIEW}.get(decision, STOPPED)
        detail = (
            f"{decision.upper()} · limit {fmt.thb(policy.get('limit'))}"
            if decision == "approve"
            else (f"{decision.upper()}")
        )
        out.append({"name": "Policy", "state": state, "detail": detail})
    status = wallet.get("status")
    draw = timeline.get("TX-4")
    if draw and status == "executed":
        out.append({"name": "Wallet", "state": DONE, "detail": "paid inside the mandate (TX-4)"})
    elif draw and status == "pending_approval":
        out.append({"name": "Wallet", "state": REVIEW, "detail": "waiting for a human approver"})
    elif draw:
        out.append(
            {"name": "Wallet", "state": STOPPED, "detail": f"blocked: {draw.get('block_reason') or status}"}
        )
    else:
        out.append({"name": "Wallet", "state": SKIPPED, "detail": "never asked to pay"})
    if status == "executed":
        out.append(
            {
                "name": "Settle",
                "state": DONE if paid else WAITING,
                "detail": "buyer paid (TX-5)" if paid else "waiting for the buyer",
            }
        )
    else:
        out.append({"name": "Settle", "state": SKIPPED, "detail": "nothing to settle"})
    return out


def verdict(view: dict, paid: bool = False) -> tuple[str, str, str]:
    """(state, headline, one sentence) for the banner above the steps."""
    policy, wallet = view.get("policy"), view.get("wallet") or {}
    timeline = {t["step"]: t for t in view.get("timeline", [])}
    if (view.get("registry") or {}).get("duplicate") or (timeline.get("TX-1") or {}).get(
        "status"
    ) == "blocked":
        reason = (timeline.get("TX-1") or {}).get("block_reason") or "DuplicateReceivable"
        return STOPPED, "Stopped: duplicate invoice", f"No money moved: {plain(reason) or reason}."
    if not policy:
        return (
            STOPPED,
            "Stopped before a credit decision",
            f"No money moved ({view.get('state') or 'unknown'}).",
        )
    decision, reasons = policy["decision"], policy.get("reasons", [])
    found = [f["headline"] for f in findings(view.get("ocr") or {}) if f["kind"] == "fraud"]
    found_line = f" The document checks found: {_join(found)}." if found else ""
    if decision == "reject":
        why = _why(reasons, ("HARD.", "KO.", "REVIEW.")) or ["the credit policy said no"]
        return STOPPED, "Rejected: no money moved", f"Rejected because {_join(why)}.{found_line}"
    if decision == "review":
        why = _why(reasons, ("HARD.", "REVIEW.", "KO.")) or ["a rule asked for a person to look"]
        return (
            REVIEW,
            "Sent to a person: no money moved",
            f"Held for human review because {_join(why)}.{found_line}",
        )
    status = wallet.get("status")
    if status == "executed":
        chosen = next((o for o in view.get("offers", []) if o.get("chosen")), None)
        lender = f" by {chosen['lender']}" if chosen else ""
        tail = " The buyer has paid and the advance is settled." if paid else ""
        return (
            DONE,
            "Funded inside the rules",
            f"Read, checked as new, approved by the credit policy and paid{lender} "
            f"within the SME's mandate.{tail}",
        )
    if status == "pending_approval":
        return REVIEW, "Approved, waiting for a human", "The draw is above the SME's human-review line."
    reason = (timeline.get("TX-4") or {}).get("block_reason") or wallet.get("block_reason") or status
    return (
        STOPPED,
        "Blocked by the wallet",
        f"Approved, but the wallet refused to pay: {plain(reason) or reason}.",
    )
