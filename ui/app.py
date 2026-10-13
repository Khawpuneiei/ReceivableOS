"""ReceivableOS demo screen (brief section 12). Run: streamlit run ui/app.py --server.port 3000

One screen, top to bottom: mandate, invoice, decision, offers, on-chain timeline, attacks, footer.
UI_MODE=fixtures (the default) renders the saved responses in ui/fixtures/ with no backend.
UI_MODE=live talks to the orchestrator only (ui/client.py); any part it can't serve yet falls back to the
fixture with a visible label, and an unreachable orchestrator shows an amber banner instead of crashing.
Every number on screen comes from a response or a fixture; nothing is typed into the UI.
All text from the invoice is untrusted, so it is HTML-escaped before it is shown.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

import client as orch
import format as fmt
import story
import streamlit as st

HERE = Path(__file__).resolve().parent
DEMO_DIR = HERE.parent / "data" / "invoices" / "demo"
DEMO_INVOICE = DEMO_DIR / "01_happy.pdf"  # a real PDF; OCR refuses the old .txt sample
# One-click cases: (key, button, file in data/invoices/demo/, what it shows). Built by the AI engineers.
DEMO_CASES = (
    ("happy", "Happy invoice", "01_happy.pdf", "a clean invoice: read, approved and paid"),
    (
        "injected",
        "Injected instructions",
        "02_injected.pdf",
        "text in the PDF tells the AI to approve and pay",
    ),
    ("inflated", "Inflated amount", "03_inflated.pdf", "the total is bigger than its line items"),
    (
        "duplicate",
        "Duplicate (re-saved PDF)",
        "04_duplicate.pdf",
        "the happy invoice saved again as a new file",
    ),
)
FIXTURES = HERE / "fixtures"
ATTACKS = ("a1", "a2", "a3", "a4", "a5", "a6")
ATTACK_LABELS = {
    "a1": "A1 Injection + payee swap",
    "a2": "A2 Duplicate invoice",
    "a3": "A3 Quote above APR cap",
    "a4": "A4 Draw above limit",
    "a5": "A5 Expired KYB",
    "a6": "A6 Mandate expired / paused",
}
MANDATE_FIELDS = (
    ("max_ltv", "Max advance", "pct"),
    ("max_apr", "Max APR", "pct"),
    ("max_predicted_default", "Max buyer PD", "pct"),
    ("human_review_above", "Human review at or above", "thb"),
    ("max_amount_per_tx", "Per transaction", "thb"),
    ("daily_cap", "Daily cap", "thb"),
    ("expires_at", "Expires", "text"),
)

CSS = """
<style>
html, body, [class*="css"], .stMarkdown p, .stMarkdown li { font-size: 18px; }
.badge { display:inline-block; padding:4px 14px; border-radius:6px; color:#fff; font-weight:700; }
.big { font-size: 34px; padding: 8px 28px; }
.chip { display:inline-block; padding:2px 10px; margin:2px; border-radius:12px; color:#fff; font-size:15px; }
.row { padding:8px 12px; margin:4px 0; border-left:6px solid; border-radius:4px;
       background:rgba(127,127,127,.08); }
.gauge { position:relative; height:22px; background:rgba(127,127,127,.18); border-radius:4px; }
.gauge .fill { position:absolute; height:100%; border-radius:4px; }
.gauge .cap { position:absolute; top:-4px; height:30px; border-left:3px dashed #c62828; }
code { font-size: 15px; }
.verdict { padding:14px 20px; border-radius:8px; color:#fff; margin:8px 0 12px; }
.verdict b { font-size: 28px; display:block; }
.steps { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
.step { flex:1 1 140px; border-top:8px solid; border-radius:6px; padding:8px 10px;
        background:rgba(127,127,127,.08); min-width:140px; }
.step .n { font-weight:700; } .step .d { font-size:15px; }
.step .i { display:inline-block; width:24px; height:24px; border-radius:12px; color:#fff;
           text-align:center; font-weight:700; margin-right:6px; line-height:24px; }
</style>
"""


def esc(value) -> str:
    return html.escape(str(value))


def badge(text: str, state: str | None = None, big: bool = False) -> str:
    cls = "badge big" if big else "badge"
    return f'<span class="{cls}" style="background:{fmt.state_colour(state or text)}">{esc(text)}</span>'


def row(body: str, state: str) -> str:
    return f'<div class="row" style="border-color:{fmt.state_colour(state)}">{body}</div>'


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def mode() -> str:
    return os.getenv("UI_MODE", "fixtures").strip().lower()


def load_view() -> dict:
    """The view model: mandate_text, mandate, ocr, registry, policy, offers, wallet, timeline, repay."""
    return st.session_state.get("view") or load_fixture("happy")


def live() -> bool:
    return mode() == "live"


def fixture_label(view: dict, part: str) -> None:
    if view.get("source") == "orchestrator" and part in view.get("from_fixture", []):
        st.caption(f"FIXTURE: the orchestrator does not return {part} yet; showing saved data.")


def not_reached(view: dict, part: str) -> bool:
    """True (and says so on screen) when the live flow stopped before this part ran."""
    if part not in view.get("not_reached", []):
        return False
    st.markdown(
        row(f"Not reached: the flow stopped earlier (<b>{esc(view.get('state'))}</b>).", "unknown"),
        unsafe_allow_html=True,
    )
    return True


def run_file(content: bytes, name: str, case: str | None = None) -> None:
    """POST one invoice to /flow/run and put the result on screen; errors become a readable notice."""
    try:
        raw = orch.Orchestrator().run_flow(content, name)
        st.session_state.view = orch.to_view(raw, load_fixture("happy"))
        st.session_state.update(paid=False, approved=False, notice=None, extra_tx=[], case=case or name)
        st.session_state.ran.add(case or name)
    except orch.ServiceError as exc:
        st.session_state.notice = f"The flow stopped with an error: {exc.plain}. Showing the saved demo."
    except (orch.Unavailable, orch.Unsupported, ValueError) as exc:
        st.session_state.notice = (
            f"Orchestrator unavailable at {orch.base_url()} ({exc}). Showing the saved demo."
        )


def run_case(case: str, filename: str) -> None:
    if case == "duplicate" and "happy" not in st.session_state.ran:
        run_file(DEMO_INVOICE.read_bytes(), DEMO_INVOICE.name, "happy")  # something to be a duplicate of
    run_file((DEMO_DIR / filename).read_bytes(), filename, case)


def run_controls() -> None:
    """Live mode: one click per demo case, or an uploaded invoice, through the orchestrator."""
    st.markdown("**Run a demo invoice through the live flow**")
    cols = st.columns(len(DEMO_CASES))
    for col, (case, label, filename, hint) in zip(cols, DEMO_CASES, strict=True):
        if col.button(label, key=f"case_{case}", type="primary" if case == "happy" else "secondary"):
            run_case(case, filename)
            st.rerun()
        col.caption(hint)
    st.caption(
        "Each invoice can be financed once: running Happy twice is blocked as a duplicate, by design. "
        "Reset the OCR demo history between rehearsals (services/ocr-ai/README.md)."
    )
    with st.expander("Or upload your own invoice"):
        upload = st.file_uploader("Invoice file", key="upload")
        if upload and st.button("Run flow with this file"):
            run_file(upload.getvalue(), upload.name)
            st.rerun()


def init_state() -> None:
    defaults = {
        "attacks": [],
        "paid": False,
        "approved": False,
        "compiled": True,
        "notice": None,
        "extra_tx": [],
        "ran": set(),
        "case": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def header(view: dict) -> None:
    chain = (view.get("wallet") or {}).get("chain") or "unknown"
    ledger_state = {"mock": "pending_approval", "fisco": "executed"}.get(chain, "unknown")
    st.markdown(
        "## ReceivableOS · AI that can move money — only inside the rules "
        + badge(f"ledger: {chain}", ledger_state),
        unsafe_allow_html=True,
    )
    if st.session_state.notice:
        st.warning(st.session_state.notice)
    if view.get("source") == "fixtures" and live():
        st.info(f"SAVED DEMO: nothing has run live yet. Run an invoice below to call {orch.base_url()}.")
    elif view.get("source") == "fixtures":
        st.info("FIXTURE MODE: saved responses from ui/fixtures/, no backend called.")
    else:
        label = {c[0]: c[1] for c in DEMO_CASES}.get(st.session_state.case, st.session_state.case)
        st.success(
            f"LIVE: {label} via the orchestrator at {orch.base_url()} · flow state {view.get('state')}"
        )


def section_flow(view: dict) -> None:
    """Where the invoice got to, in one line a judge can read from the back of the room."""
    state, headline, sentence = story.verdict(view, st.session_state.paid)
    st.markdown(
        f'<div class="verdict" style="background:{story.STATE_COLOUR[state]}"><b>{esc(headline)}</b>'
        f"{esc(sentence)}</div>",
        unsafe_allow_html=True,
    )
    cards = []
    for n, s in enumerate(story.steps(view, st.session_state.paid), 1):
        colour = story.STATE_COLOUR[s["state"]]
        cards.append(
            f'<div class="step" style="border-color:{colour}"><span class="i" style="background:{colour}">'
            f'{story.STATE_ICON[s["state"]]}</span><span class="n">{n}. {esc(s["name"])}</span>'
            f'<div class="d">{esc(s["detail"])}</div></div>'
        )
    st.markdown(f'<div class="steps">{"".join(cards)}</div>', unsafe_allow_html=True)


def section_mandate(view: dict) -> None:
    st.subheader("1. Mandate")
    text = st.text_area("The SME's rule, in plain language", view["mandate_text"], height=80)
    if st.button("Compile"):
        st.session_state.compiled = True
        if live():
            try:
                view["mandate"] = orch.Orchestrator().compile_mandate(text)
                view["from_fixture"] = [part for part in view.get("from_fixture", []) if part != "mandate"]
            except (orch.Unavailable, orch.Unsupported) as exc:
                st.warning(f"Compile not available from the orchestrator ({exc}); showing the saved mandate.")
        elif text.strip() != view["mandate_text"].strip():
            st.warning("Compiling new wording needs the orchestrator. Showing the saved demo mandate.")
    fixture_label(view, "mandate")
    if not st.session_state.compiled:
        return
    envelope, mandate = view["mandate"], view["mandate"]["mandate"]
    cells = []
    for key, label, kind in MANDATE_FIELDS:
        value = mandate.get(key)
        shown = fmt.pct(value, 0) if kind == "pct" else fmt.thb(value) if kind == "thb" else esc(value or "-")
        source = fmt.field_source(envelope, key)
        colour = fmt.GREY if source == "default" else fmt.GREEN
        cells.append(
            f'<div class="row" style="border-color:{colour}"><b>{label}</b>: {shown} '
            f'<span style="color:{colour}">({"from text" if source == "text" else source})</span></div>'
        )
    st.markdown("".join(cells), unsafe_allow_html=True)
    with st.expander("Mandate JSON (wallet field names)"):
        st.json(envelope)


def section_invoice(view: dict) -> None:
    st.subheader("2. Invoice")
    inv = view["ocr"]
    left, right = st.columns([3, 2])
    with left:
        rows = [
            ("Supplier", f"{inv['supplier']['name']} ({inv['supplier']['tax_id']})"),
            ("Buyer", f"{inv['buyer']['name']} ({inv['buyer']['tax_id']})"),
            ("Invoice no.", inv["invoice_no"]),
            ("Issued / due", f"{inv['issue_date']} / {inv['due_date']}"),
            ("Amount", fmt.thb(inv["amount"], inv["currency"])),
        ]
        st.markdown("".join(f"<b>{esc(k)}</b>: {esc(v)}<br>" for k, v in rows), unsafe_allow_html=True)
    with right:
        st.markdown(f"OCR confidence **{fmt.pct(inv['confidence'], 0)}**")
        st.progress(min(max(float(inv["confidence"]), 0.0), 1.0))
        flags = [("injection", f) for f in inv.get("injection_flags", [])]
        flags += [("fraud", f) for f in inv.get("fraud_flags", [])]
        chips = "".join(
            f'<span class="chip" style="background:{fmt.RED}">{esc(k)}: {esc(f)}</span>' for k, f in flags
        )
        clean = f'<span class="chip" style="background:{fmt.GREEN}">no injection or fraud flags</span>'
        st.markdown(f"Fraud score {esc(inv['fraud_score'])}<br>{chips or clean}", unsafe_allow_html=True)
        st.markdown(
            f"doc_hash <code>{esc(fmt.short_hash(inv['doc_hash']))}</code><br>"
            f"fingerprint <code>{esc(fmt.short_hash(inv['invoice_fingerprint']))}</code>",
            unsafe_allow_html=True,
        )


def section_decision(view: dict) -> None:
    st.subheader("3. Decision")
    d = view["policy"]
    if not d:
        st.markdown(badge("STOPPED", "blocked", big=True), unsafe_allow_html=True)
        st.markdown(f"No credit decision: the flow stopped before policy ({esc(view.get('state'))}).")
        return
    cap = float(view["mandate"]["mandate"].get("max_predicted_default", "0.05"))
    st.markdown(badge(d["decision"].upper(), d["decision"], big=True), unsafe_allow_html=True)
    a, b, c = st.columns(3)
    a.metric("Advance", fmt.pct(d["advance_rate"], 0))
    b.metric("Limit", fmt.thb(d["limit"]))
    c.metric("Fee", fmt.rate_pair(d["fee_rate"], d.get("apr")))
    pd_value = float(d.get("pd", d["risk_score"]))
    fill, line = fmt.gauge(pd_value, cap)
    st.markdown(
        f"Buyer PD **{fmt.pct(pd_value)}** against the mandate's {fmt.pct(cap, 0)} line"
        f'<div class="gauge"><div class="fill" style="width:{fill * 100:.1f}%;'
        f'background:{fmt.GREEN if pd_value <= cap else fmt.RED}"></div>'
        f'<div class="cap" style="left:{line * 100:.1f}%"></div></div>',
        unsafe_allow_html=True,
    )
    reasons = sorted(d["reasons"], key=lambda r: r.startswith("MODEL."))
    st.markdown("\n".join(f"- `{esc(code)}` {esc(text)}" for code, text in map(fmt.reason_code, reasons)))
    with st.expander("Why? Model drivers and rule trace"):
        drivers = {f["feature"]: f["contribution"] for f in d.get("top_features", [])}
        if drivers:
            st.caption("Top model drivers, in log-odds (negative lowers the predicted default)")
            st.bar_chart(drivers, horizontal=True)
        st.code("\n".join(d.get("rule_trace", [])), language=None)


def section_offers(view: dict) -> None:
    st.subheader("4. Offers")
    fixture_label(view, "offers")
    if not_reached(view, "offers"):
        return
    rows = []
    for o in view.get("offers", []):
        state = "executed" if o["chosen"] else "reject" if not o["within_mandate"] else "unknown"
        mark = "CHOSEN · " if o["chosen"] else "OUT OF MANDATE · " if not o["within_mandate"] else ""
        rows.append(
            row(
                f"<b>{mark}{esc(o['lender'])}</b>: advance {fmt.pct(o['advance_rate'], 0)}, "
                f"{fmt.pct(o['apr'])} APR, {esc(o['reason'])}",
                state,
            )
        )
    st.markdown("".join(rows) or "No quotes.", unsafe_allow_html=True)


def tx_row(t: dict) -> str:
    reason = f" · <b>{esc(t['block_reason'])}</b>" if t.get("block_reason") else ""
    label = f" <i>({esc(t['label'])})</i>" if t.get("label") else ""
    return row(
        f"<b>{esc(t['step'])}</b> {esc(t['call'])}{label} · {esc(t['status'])}{reason} · "
        f"<code>{esc(fmt.short_hash(t.get('chain_ref')))}</code>",
        t["status"],
    )


def section_chain(view: dict) -> None:
    st.subheader("5. On-chain")
    wallet = view.get("wallet") or {}
    timeline = list(view.get("timeline", []))
    if wallet.get("status") == "pending_approval" and not st.session_state.approved:
        st.warning(f"Waiting for human approval ({wallet.get('approvals_required', 1)} required)")
        if st.button("Approve"):
            action(lambda o: o.confirm(wallet["tx_id"]), "TX-4", "Approve", "approved")
    if st.session_state.paid and view.get("repay"):
        timeline.append(view["repay"])
    timeline += st.session_state.extra_tx
    st.markdown("".join(tx_row(t) for t in timeline) or "No transactions.", unsafe_allow_html=True)
    if "wallet" in view.get("not_reached", []):
        st.caption("The wallet was never asked to pay: no credit approval (TX-2) and no draw (TX-4).")
    if wallet.get("status") == "executed" and not st.session_state.paid and st.button("Buyer paid"):
        action(lambda o: o.repay(view), "TX-5", "Buyer paid", "paid")


def action(call, step: str, label: str, flag: str) -> None:
    """Approve / Buyer paid: through the orchestrator when live; the fixture otherwise or when unsupported."""
    st.session_state[flag] = True
    if live() and st.session_state.get("view"):
        try:
            st.session_state.extra_tx.append(orch.action_row(call(orch.Orchestrator()), step, label))
        except (orch.Unavailable, orch.Unsupported, KeyError) as exc:
            st.session_state.notice = f"{label}: not available from the orchestrator ({exc}); fixture shown."
            if flag == "paid":
                st.session_state.extra_tx.append({**load_fixture("happy")["repay"], "label": "fixture"})
    st.rerun()


def run_attack(case: str) -> dict:
    saved = load_fixture(case)
    if not live():
        return saved
    try:
        return orch.attack_row(orch.Orchestrator().attack(case), saved)
    except (orch.Unavailable, orch.Unsupported) as exc:
        return {**saved, "label": f"fixture: orchestrator has no attack route ({exc})"}


def section_attacks() -> None:
    st.subheader("6. Attacks")
    cols = st.columns(len(ATTACKS))
    for col, case in zip(cols, ATTACKS, strict=True):
        if col.button(ATTACK_LABELS[case], key=f"attack_{case}"):
            st.session_state.attacks.append(run_attack(case))
    for a in reversed(st.session_state.attacks):
        policy = f" · policy {esc(a['policy_decision'])}" if a.get("policy_decision") else ""
        codes = ", ".join(esc(c) for c in a.get("policy_reasons", []))
        stopped = a["status"] in ("blocked", "failed", "reject", "review")
        label = f" <i>({esc(a['label'])})</i>" if a.get("label") else ""
        why = story.plain(a.get("block_reason"))
        why_line = f"<br>Why: {esc(why)}." if why and stopped else ""
        st.markdown(
            row(
                f"<b>{'BLOCKED' if stopped else esc(a['status']).upper()} {esc(a['case'])}</b>: "
                f"{esc(a['title'])}{label}<br>"
                f"stopped by <b>{esc(a['stopped_by'])}</b>"
                f"{policy} {codes} · revert <b>{esc(a.get('block_reason') or '-')}</b> · "
                f"<code>{esc(fmt.short_hash(a.get('chain_ref')))}</code>{why_line}",
                "blocked" if stopped else a["status"],
            ),
            unsafe_allow_html=True,
        )


def footer(view: dict) -> None:
    d = view["policy"] or {}
    audit = (view.get("wallet") or {}).get("audit_ref", "-")
    st.divider()
    st.caption(
        f"policy_version {d.get('policy_version', '-')} · model_version {d.get('model_version', '-')} · "
        f"decision_hash {fmt.short_hash(d.get('decision_hash'))} · audit {audit}"
    )


def main() -> None:
    st.set_page_config(page_title="ReceivableOS demo", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    view = load_view()
    header(view)
    if live():
        run_controls()
    section_flow(view)
    section_mandate(view)
    section_invoice(view)
    section_decision(view)
    section_offers(view)
    section_chain(view)
    section_attacks()
    footer(view)


if __name__ == "__main__":  # streamlit runs the script as __main__; tests import it without rendering
    main()
