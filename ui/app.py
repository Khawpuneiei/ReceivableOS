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
import merkle
import story
import streamlit as st

HERE = Path(__file__).resolve().parent
DEMO_DIR = HERE.parent / "data" / "invoices" / "demo"
DEMO_INVOICE = DEMO_DIR / "01_happy.pdf"  # a real PDF; OCR refuses the old .txt sample
# One-click cases: (key, button, file in data/invoices/demo/, what it shows). Built by the AI engineers.
DEMO_CASES = (
    ("happy", "Happy invoice", "01_happy.pdf", "a clean invoice: read, approved and paid"),
    ("injected", "Injected instructions", "02_injected.pdf", "the PDF tells the AI to approve and pay"),
    ("inflated", "Inflated amount", "03_inflated.pdf", "the total is bigger than its line items"),
    (
        "duplicate",
        "Duplicate (re-saved PDF)",
        "04_duplicate.pdf",
        "the happy invoice, re-saved as a new file",
    ),
    # Shown only once ocr-ai's tamper, QR, words, terms and related-party checks land with their demo PDFs
    # (see case_available).
    ("tampered", "Tampered PDF", "05_tampered.pdf", "text was added to the PDF after it was made"),
    ("qr_swap", "QR swap", "06_qr_swap.pdf", "the payment QR pays someone other than the supplier"),
    ("words", "Amount in words", "07_words_mismatch.pdf", "the total in words disagrees with the digits"),
    ("terms", "Payment terms", "08_terms_mismatch.pdf", "the due date breaks the invoice's own terms"),
    ("self_invoice", "Self-invoice", "09_self_invoice.pdf", "the supplier billed its own branch"),
)
CASES_PER_ROW = 4
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
MIN_CONFIDENCE = 0.80  # policy-ai's hard rule: below this the invoice goes to review (root CLAUDE.md)
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
.why { font-size:15px; color:#555; }
.row { padding:8px 12px; margin:4px 0; border-left:6px solid; border-radius:4px;
       background:rgba(127,127,127,.08); }
.gauge { position:relative; height:22px; background:rgba(127,127,127,.18); border-radius:4px; }
.gauge .fill { position:absolute; height:100%; border-radius:4px; }
.gauge .cap { position:absolute; top:-4px; height:30px; border-left:3px dashed #c62828; }
code { font-size: 15px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); column-gap:8px; }
.verdict { padding:14px 20px; border-radius:8px; color:#fff; margin:8px 0 12px; }
.verdict b { font-size: 28px; display:block; }
.steps { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
.step { flex:1 1 0; border-top:8px solid; border-radius:6px; padding:8px 10px;
        background:rgba(127,127,127,.08); min-width:118px; }
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
    if view.get("source") in ("orchestrator", "saved") and part in view.get("from_fixture", []):
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


def run_file(content: bytes, name: str, case: str | None = None) -> str | None:
    """POST one invoice to /flow/run and put the result on screen. Returns a readable error, or None."""
    try:
        raw = orch.Orchestrator().run_flow(content, name)
        st.session_state.view = orch.to_view(raw, load_fixture("happy"))
    except orch.ServiceError as exc:
        return f"The flow stopped with an error: {exc.plain}."
    except (orch.Unavailable, orch.Unsupported, ValueError) as exc:
        return f"Orchestrator unavailable at {orch.base_url()} ({exc})."
    st.session_state.update(paid=False, approved=False, notice=None, extra_tx=[], case=case or name)
    st.session_state.ran.add(case or name)
    return None


def show_saved_run(case: str, notice: str | None) -> None:
    """The case's /flow/run response recorded from the live stack (ui/fixtures/runs/), labelled SAVED."""
    raw = json.loads((FIXTURES / "runs" / f"{case}.json").read_text(encoding="utf-8"))
    happy = load_fixture("happy")
    view = orch.to_view(raw, happy)
    view.update(source="saved", repay={**happy["repay"], "label": "saved"})
    st.session_state.view = view
    st.session_state.update(paid=False, approved=False, notice=notice, extra_tx=[], case=case)


def case_available(case: str, filename: str) -> bool:
    """Live: the demo PDF is in the repo. Fixture mode: a saved run of the case exists."""
    if live():
        return (DEMO_DIR / filename).exists()
    return (FIXTURES / "runs" / f"{case}.json").exists()


def run_case(case: str, filename: str) -> None:
    """Live: run the case's PDF; if the stack fails, show the saved run of the same case instead."""
    if not live():
        show_saved_run(case, None)
        return
    if case == "duplicate" and "happy" not in st.session_state.ran:
        run_file(DEMO_INVOICE.read_bytes(), DEMO_INVOICE.name, "happy")  # something to be a duplicate of
    error = run_file((DEMO_DIR / filename).read_bytes(), filename, case)
    if error and (FIXTURES / "runs" / f"{case}.json").exists():
        show_saved_run(case, f"{error} Showing the saved run of this case instead.")
    elif error:
        st.session_state.notice = error


def run_all() -> None:
    """Judge mode: every available case in order (Happy first, so Duplicate has something to repeat)."""
    board = []
    for case, label, filename, _ in [c for c in DEMO_CASES if case_available(c[0], c[2])]:
        run_case(case, filename)
        view = load_view()
        if st.session_state.case != case:  # it failed and there is no saved run to show instead
            board.append(
                {
                    "case": case,
                    "label": label,
                    "state": story.STOPPED,
                    "headline": "Could not run",
                    "sentence": st.session_state.notice or "",
                    "saved": False,
                    "view": None,
                }
            )
            continue
        state, headline, sentence = story.verdict(view)
        saved = view.get("source") in ("fixtures", "saved")
        board.append(
            {
                "case": case,
                "label": label,
                "state": state,
                "headline": headline,
                "sentence": sentence,
                "saved": saved,
                "view": view,
            }
        )
    st.session_state.scoreboard = board


def section_scoreboard() -> None:
    """One line per case after judge mode, each with a button to open that run below."""
    board = st.session_state.scoreboard
    if not board:
        return
    funded = sum(r["state"] == story.DONE for r in board)
    held = sum(r["state"] == story.REVIEW for r in board)
    summary = f"**Judge mode: {len(board)} invoices, {funded} funded, {held} sent to a person, "
    summary += f"{len(board) - funded - held} stopped.**"
    if funded == 1 and board[0]["case"] == "happy" and board[0]["state"] == story.DONE:
        summary += " Only one invoice moved money; every forged one was held or stopped."
    st.markdown(summary)
    for r in board:
        colour = story.STATE_COLOUR[r["state"]]
        tag = " (saved demo)" if r["saved"] else ""
        left, right = st.columns([6, 1], vertical_alignment="center")
        left.markdown(
            f'<div class="row" style="border-color:{colour}"><b>{esc(r["label"])}</b> · '
            f'<span class="chip" style="background:{colour}">{esc(r["headline"] + tag)}</span>'
            f'<br><span class="why">{esc(r["sentence"])}</span></div>',
            unsafe_allow_html=True,
        )
        if r["view"] and right.button("Show", key=f"show_{r['case']}", width="stretch"):
            st.session_state.update(view=r["view"], case=r["case"], paid=False, approved=False, extra_tx=[])
            st.rerun()


def run_controls() -> None:
    """One click per demo case: live through the orchestrator, or the saved run in fixture mode."""
    title = "Run a demo invoice through the live flow" if live() else "Show a recorded run of a demo invoice"
    st.markdown(f"**{title}**")
    cases = [c for c in DEMO_CASES if case_available(c[0], c[2])]
    for start in range(0, len(cases), CASES_PER_ROW):
        cols = st.columns(CASES_PER_ROW)
        row = cases[start : start + CASES_PER_ROW]
        for col, (case, label, filename, hint) in zip(cols, row, strict=False):
            kind = "primary" if case == "happy" else "secondary"
            if col.button(label, key=f"case_{case}", type=kind, width="stretch"):
                run_case(case, filename)
                st.rerun()
            col.caption(hint)
    if st.button("Judge mode: run every case in order", key="run_all", type="primary"):
        with st.spinner("Running every demo invoice through the flow..."):
            run_all()
        st.rerun()
    if not live():
        return
    st.caption(
        "Each invoice can be financed once: running Happy twice is blocked as a duplicate, by design. "
        "Reset the OCR demo history between rehearsals (services/ocr-ai/README.md)."
    )
    with st.expander("Or upload your own invoice"):
        upload = st.file_uploader("Invoice file", key="upload")
        if upload and st.button("Run flow with this file"):
            error = run_file(upload.getvalue(), upload.name)
            if error:
                st.session_state.notice = f"{error} Showing the saved demo."
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
        "scoreboard": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def header(view: dict) -> None:
    chain = (view.get("wallet") or {}).get("chain") or "unknown"
    ledger_state = {"mock": "pending_approval", "fisco": "executed"}.get(chain, "unknown")
    st.markdown(
        "## ReceivableOS · AI that can move money — only inside the rules "
        + f'<span class="badge" style="font-size:18px;vertical-align:middle;'
        f'background:{fmt.state_colour(ledger_state)}">ledger: {esc(chain)}</span>',
        unsafe_allow_html=True,
    )
    if st.session_state.notice:
        st.warning(st.session_state.notice)
    if view.get("source") == "saved":
        label = {c[0]: c[1] for c in DEMO_CASES}.get(st.session_state.case, st.session_state.case)
        st.info(
            f"SAVED RUN: {label}, recorded from the live stack on the mock ledger. Nothing was called now."
        )
    elif view.get("source") == "fixtures" and live():
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
    if view.get("source") in ("fixtures", "saved"):
        headline += " (saved demo)"  # never let a saved result read as this run's
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
    st.markdown(f'<div class="grid">{"".join(cells)}</div>', unsafe_allow_html=True)
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
        confidence = min(max(float(inv["confidence"]), 0.0), 1.0)
        ok = confidence >= MIN_CONFIDENCE
        st.markdown(
            f"OCR confidence <b>{fmt.pct(confidence, 0)}</b> against the {fmt.pct(MIN_CONFIDENCE, 0)} minimum"
            f'<div class="gauge"><div class="fill" style="width:{confidence * 100:.1f}%;'
            f'background:{fmt.GREEN if ok else fmt.AMBER}"></div>'
            f'<div class="cap" style="left:{MIN_CONFIDENCE * 100:.0f}%"></div></div>',
            unsafe_allow_html=True,
        )
        flags = [("injection", f) for f in inv.get("injection_flags", [])]
        flags += [("fraud", f) for f in inv.get("fraud_flags", [])]
        chips = "".join(
            f'<span class="chip" style="background:{fmt.RED}">{esc(k)}: {esc(f)}</span>' for k, f in flags
        )
        clean = f'<span class="chip" style="background:{fmt.GREEN}">no injection or fraud flags</span>'
        st.markdown(f"Fraud score {esc(inv['fraud_score'])}<br>{chips or clean}", unsafe_allow_html=True)
        found = story.findings(inv)
        if found:
            lines = []
            for f in found:
                weight = f" <i>(+{esc(f['weight'])} fraud score)</i>" if f.get("weight") else ""
                detail = (
                    f"<br><span style='font-size:15px'>{esc(f['detail'])}</span>" if f.get("detail") else ""
                )
                headline = f["headline"][:1].upper() + f["headline"][1:]  # keep "QR", "PDF" as written
                lines.append(row(f"<b>{esc(headline)}</b>{weight}{detail}", "review"))
            st.markdown("<b>What the document checks found</b>" + "".join(lines), unsafe_allow_html=True)
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
    c.metric("Fee", f"{fmt.pct(d['apr'])} APR" if d.get("apr") else fmt.rate_pair(d["fee_rate"], None))
    if d.get("apr"):
        c.caption(f"= {fmt.pct(d['fee_rate'])} per 30 days")
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
    lines = []
    for code, text in map(fmt.reason_code, reasons):
        words = story.plain(code)
        lines.append(f"- `{esc(code)}` " + (f"**{esc(words)}**: {esc(text)}" if words else esc(text)))
    st.markdown("\n".join(lines))
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
    audit_check(view)


def short(h: str | None) -> str:
    """0xcec8...752e; a chain prefix such as mock: is kept whole."""
    prefix, _, value = str(h).rpartition(":")
    value = f"{value[:6]}...{value[-4:]}" if len(value) > 14 else value
    return f"{prefix}:{value}" if prefix else value


def audit_check(view: dict) -> None:
    """Fetch the wallet's Merkle proof for the draw and check it here, so the screen does not take the
    wallet's word for it (ui/merkle.py). Live runs only; hidden before the draw executed."""
    wallet = view.get("wallet") or {}
    ref = wallet.get("audit_ref")
    if view.get("source") != "orchestrator" or wallet.get("status") != "executed" or not ref:
        return
    if st.button("Check this payment in the audit log", key="audit_check"):
        try:
            bundle = orch.Orchestrator().audit_proof(ref)
            st.session_state.proof = {"ref": ref, "bundle": bundle, "problems": merkle.check(bundle)}
        except orch.Unsupported:
            st.session_state.proof = {"ref": ref, "bundle": None, "problems": ["unsupported"]}
        except (orch.ServiceError, orch.Unavailable, KeyError, ValueError) as exc:
            plain_text = getattr(exc, "plain", None) or str(exc)
            st.session_state.proof = {"ref": ref, "bundle": None, "problems": [plain_text]}
    proof = st.session_state.get("proof")
    if not proof or proof["ref"] != ref:
        return
    bundle, problems = proof["bundle"], proof["problems"]
    if problems == ["unsupported"]:
        body, state = "This wallet version does not serve Merkle audit proofs yet.", "unknown"
    elif bundle is None or problems:
        body, state = f"<b>Audit check failed</b>: {esc('; '.join(problems))}.", "blocked"
    else:
        e = bundle["entry"]
        anchored = (
            f" That root is anchored on chain ({esc(short(bundle.get('chain_ref')))})."
            if bundle.get("anchored")
            else " Not on chain yet: the wallet anchors the root when the buyer pays, then check again."
        )
        body = (
            f"<b>Verified on this screen</b>: audit entry #{esc(e['seq'])} ({esc(e['action'])}, "
            f"{esc(e['event'])}) matches its own hash and is in the wallet's Merkle log of "
            f"{esc(bundle['tree_size'])} entries ({len(bundle['proof'])}-hash path, root "
            f"<code>{esc(short(bundle['root']))}</code>).{anchored}"
        )
        state = "executed"
    st.markdown(row(body, state), unsafe_allow_html=True)


def action(call, step: str, label: str, flag: str) -> None:
    """Approve / Buyer paid: through the orchestrator when live; the fixture otherwise or when unsupported."""
    st.session_state[flag] = True
    if live() and (st.session_state.get("view") or {}).get("source") == "orchestrator":
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


def attack_row_html(a: dict) -> str:
    """One attack: verdict and title, a plain Why, then who stopped it, the deciding policy codes, the ref."""
    stopped = a["status"] in ("blocked", "failed", "reject", "review")
    label = a.get("label") or ""
    source = (
        badge("LIVE", "executed")
        if label == "live"
        else badge("SAVED", "unknown") + f" <i>({esc(label)})</i>"
        if label
        else ""
    )
    why = story.plain(a.get("block_reason"))
    deciding = [c for c in a.get("policy_reasons", []) if c.startswith(("HARD.", "KO.", "REVIEW."))]
    policy = (
        f" · policy <b>{esc(a['policy_decision'])}</b>"
        + (f" ({', '.join(esc(c) for c in deciding)})" if deciding else "")
        if a.get("policy_decision")
        else ""
    )
    ref = a.get("chain_ref")
    where = f"<code>{esc(fmt.short_hash(ref))}</code>" if ref else "stopped before the ledger"
    return row(
        f"<b>{'BLOCKED' if stopped else esc(a['status']).upper()} {esc(a['case'])}</b>: {esc(a['title'])} "
        f"{source}<br>"
        + (f"Why: {esc(why)}.<br>" if why and stopped else "")
        + f'<span style="font-size:15px">stopped by <b>{esc(a["stopped_by"])}</b>{policy} · '
        f"code <b>{esc(a.get('block_reason') or '-')}</b> · {where}</span>",
        "blocked" if stopped else a["status"],
    )


def section_attacks() -> None:
    st.subheader("6. Attacks")
    st.caption(
        "Each button tries to make the agent move money it should not. Every one must come back BLOCKED."
    )
    for start in range(0, len(ATTACKS), 3):
        cols = st.columns(3)
        for col, case in zip(cols, ATTACKS[start : start + 3], strict=True):
            if col.button(ATTACK_LABELS[case], key=f"attack_{case}", width="stretch"):
                st.session_state.attacks.append(run_attack(case))
    for a in reversed(st.session_state.attacks):
        st.markdown(attack_row_html(a), unsafe_allow_html=True)


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
    run_controls()
    section_scoreboard()
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
