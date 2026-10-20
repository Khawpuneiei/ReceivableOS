"""ReceivableOS demo site (brief section 12). Run: streamlit run ui/app.py --server.port 3000

Six pages behind a top nav: Home (hero, demo cases, where the invoice got to), Invoice, Credit decision,
My rule, Ledger and Security tests. This file is the frame every page shares (style, status banner, footer)
and holds each page's renderer; ui/views/*.py are one-line page files that call them.
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
from decimal import Decimal, InvalidOperation
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
    ("injected", "Injected instructions", "02_injected.pdf", "the PDF tells the AI to approve and pay"),
    ("inflated", "Inflated amount", "03_inflated.pdf", "the total is bigger than its line items"),
    (
        "duplicate",
        "Duplicate (re-saved PDF)",
        "04_duplicate.pdf",
        "the happy invoice, re-saved as a new file",
    ),
    # Shown only once ocr-ai's tamper, QR, amount-in-words and terms checks land with their demo PDFs
    # (see case_available).
    ("tampered", "Tampered PDF", "05_tampered.pdf", "text was added to the PDF after it was made"),
    ("qr_swap", "QR swap", "06_qr_swap.pdf", "the payment QR pays someone other than the supplier"),
    ("words", "Amount in words", "07_words_mismatch.pdf", "the total in words disagrees with the digits"),
    ("terms", "Payment terms", "08_terms_mismatch.pdf", "the due date breaks the invoice's own terms"),
)
CASES_PER_ROW = 4
CASE_KEYS = tuple(c[0] for c in DEMO_CASES)
FIXTURES = HERE / "fixtures"
ATTACKS = ("a1", "a2", "a3", "a4", "a5")
ATTACK_LABELS = {
    "a1": "A1 Injection + payee swap",
    "a2": "A2 Duplicate invoice",
    "a3": "A3 Quote above APR cap",
    "a4": "A4 Draw above limit",
    "a5": "A5 Expired KYB",
}
# Top nav, in order: (page file, title, icon, one line for the Home page's "Look closer" links).
PAGES = (
    ("views/home.py", "Home", ":material/home:", ""),
    ("views/invoice.py", "Invoice", ":material/description:", "What we read and how we checked it"),
    ("views/decision.py", "Credit decision", ":material/query_stats:", "Advance, price and why"),
    ("views/rule.py", "My rule", ":material/rule:", "Your rule in your words, and what the agent enforces"),
    ("views/ledger.py", "Ledger", ":material/receipt_long:", "Every transaction the wallet recorded"),
    ("views/security.py", "Security tests", ":material/shield:", "Five attacks, each one blocked"),
)
MIN_CONFIDENCE = 0.80
MAX_FRAUD = 0.30  # policy-ai's hard rule: at or above this the invoice is rejected (root CLAUDE.md)
BRAND = "#1a4f99"  # a blocked attack is a defence that worked: brand blue, not alarm red
STOPPED_STATUSES = ("blocked", "failed", "reject", "review")
# Step icons, drawn at one stroke weight and coloured by currentColor (never text glyphs).
STATE_PATH = {
    story.DONE: "M5 12.5l4.5 4.5L19 7.5",
    story.REVIEW: "M12 7v6M12 17v.5",
    story.STOPPED: "M7 7l10 10M17 7L7 17",
    story.SKIPPED: "M7 12h10",
    story.WAITING: "M12 7v5l3 2",
}  # policy-ai's hard rule: below this the invoice goes to review (root CLAUDE.md)
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600\
&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root { --brand:#1a4f99; --brand-hover:#143d78; --brand-soft:#aedaff; --brand-tint:#eaf4ff; --accent:#d80c18;
        --ink:#0b1f33; --ink2:#344054; --ink3:#5f6b7a; --line:#e3e8ee; --canvas:#f4f7fb; --subtle:#f2f4f7; }
* { -webkit-font-smoothing: antialiased; }
.stApp { background: var(--canvas); }
html, body, .stApp, .stMarkdown, .stMarkdown p, .stMarkdown li, button, input, textarea {
  font-family: 'IBM Plex Sans Thai', 'IBM Plex Sans', system-ui, sans-serif;
  font-variant-numeric: tabular-nums lining-nums; color: var(--ink); }
.stMarkdown p, .stMarkdown li { font-size: 16px; line-height: 1.5; }
.block-container { max-width: 1200px; padding-top: 4.5rem; }
[data-testid="stHeader"] { background: transparent; }
h1, h2, h3 { color: var(--ink); font-weight: 600 !important; letter-spacing: -0.01em; }
h1, h2, h3, .headline, .verdict b { text-wrap: balance; }
.lede, .why, .verdict, .row, .tally { text-wrap: pretty; }
.nw { white-space: nowrap; }
::selection { background: var(--brand-soft); color: var(--ink); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  font-size: 14px !important; color: var(--ink3) !important; opacity: 1 !important; }
a:focus-visible, [data-testid="stTopNavLink"]:focus-visible { outline: 2px solid var(--brand);
  outline-offset: 2px; border-radius: 6px; }
h3 { font-size: 18px !important; margin: 0; padding: 0; }
code, .mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 13px;
  background: var(--subtle); color: var(--ink2) !important; padding: 1px 6px; border-radius: 6px; }
.hero { position:relative; margin:0 0 56px; padding:22px 24px 72px; border-radius:16px; color:#fff;
  background:var(--brand); }
.hero .top { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.hero .mark { width:38px; height:38px; border-radius:10px; background:#fff; color:var(--brand);
  font-weight:600; display:flex; align-items:center; justify-content:center; font-size:16px; }
.hero .name { font-size:20px; font-weight:600; line-height:1.2; color:#fff; }
.hero .tag { font-size:13px; color:var(--brand-soft); }
.hero .spacer { flex:1; }
.hero .pill { display:inline-block; padding:4px 12px; border-radius:999px; font-size:13px; font-weight:500;
  background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.35); color:#fff; }
.hero .body { display:flex; flex-wrap:wrap; gap:20px 40px; align-items:flex-end; margin-top:24px; }
.hero .pitch { flex:1 1 440px; min-width:0; } .hero .case { flex:0 1 380px; min-width:0; }
.hero .headline { font-size:36px; font-weight:600; line-height:1.1; letter-spacing:-0.02em;
  color:#fff; max-width:760px; }
.hero .lede { margin-top:10px; font-size:17px; line-height:1.5; color:#dcecff; max-width:640px; }
.hero .greet { font-size:14px; color:#dcecff; }
.head { margin:4px 0 20px; } .head h1 { font-size:32px; margin:0; padding:0; }
.head .sub { font-size:15px; color:var(--ink2); margin-top:4px; }
.hero .amt { font-size:32px; font-weight:600; line-height:1.15; color:#fff; letter-spacing:-0.01em; }
.hero .sub { font-size:14px; color:var(--brand-soft); margin-top:2px; }
.tiles { position:absolute; left:16px; right:16px; bottom:-44px; display:grid; gap:10px;
  grid-template-columns:repeat(4, 1fr); }
.tile { background:#fff; border:1px solid rgba(11,31,51,.06); border-radius:12px; padding:12px 14px;
  color:var(--ink); box-shadow:0 1px 2px rgba(11,31,51,.06), 0 8px 24px rgba(11,31,51,.10);
  animation:rise .4s cubic-bezier(.2,0,0,1) both; }
.tile:nth-child(2) { animation-delay:.06s; } .tile:nth-child(3) { animation-delay:.12s; }
.tile:nth-child(4) { animation-delay:.18s; }
.tile .chip { margin:2px 0 0; font-size:15px; font-weight:600; }
.tile .k { font-size:12px; color:var(--ink3); }
.tile .v { font-size:18px; font-weight:600; margin-top:2px; white-space:nowrap; }
.tile .v.on { color:var(--brand); }
.sec { display:flex; align-items:center; gap:10px; margin:28px 0 8px; }
.sec .bar { width:4px; height:20px; border-radius:2px; background:var(--brand); }
.sec b { font-size:18px; font-weight:600; }
.badge { display:inline-block; padding:4px 12px; border-radius:999px; font-weight:600; font-size:14px;
  border:1px solid; }
.big { font-size: 24px; padding: 6px 20px; }
.chip { display:inline-block; padding:2px 10px; margin:2px; border-radius:999px; font-size:13px;
  font-weight:500; border:1px solid; }
.why { font-size:14px; color:var(--ink3); }
.row { display:flex; gap:12px; align-items:flex-start; padding:12px 16px; margin:6px 0;
  border:1px solid var(--line); border-radius:10px; background:#fff;
  animation:rise .18s cubic-bezier(.2,0,0,1) both; }
.row .dot { flex:none; width:10px; height:10px; border-radius:50%; margin-top:7px; }
.tally { padding:14px 18px; margin:8px 0; border-radius:12px; font-size:18px; font-weight:600;
  background:var(--brand-tint); border:1px solid var(--brand-soft); color:var(--brand-hover);
  animation:rise .24s cubic-bezier(.2,0,0,1) both; }
table.items { width:100%; border-collapse:collapse; font-size:15px; margin:10px 0 4px; }
table.items th { text-align:left; font-size:12px; font-weight:600; color:var(--ink3); padding:6px 8px;
  border-bottom:1px solid var(--line); }
table.items td { padding:8px; border-bottom:1px solid var(--line); } table.items .n { text-align:right; }
.gauge { position:relative; height:10px; background:var(--subtle); border-radius:999px; margin:8px 0 14px; }
.gauge .fill { position:absolute; height:100%; border-radius:999px; }
.gauge .cap { position:absolute; top:-5px; height:20px; border-left:2px dashed var(--ink2); }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:8px; }
.verdict { padding:18px 22px; border-radius:12px; margin:8px 0 12px; border:1px solid;
  animation:rise .24s cubic-bezier(.2,0,0,1) both; }
.verdict b { font-size: 24px; font-weight:600; display:block; margin-bottom:4px; }
.steps { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
.step { flex:1 1 0; border:1px solid var(--line); border-radius:10px; padding:10px 12px;
        background:#fff; min-width:130px; }
.step .n { font-weight:600; } .step .d { font-size:14px; color:var(--ink3); line-height:1.4; }
.step .i { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px;
           border-radius:11px; border:1px solid; margin-right:6px; vertical-align:-5px; }
.step .i svg { width:14px; height:14px; }
@keyframes rise { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }
@media (prefers-reduced-motion: reduce) { .tile, .row, .tally, .verdict { animation:none; } }
[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:12px;
  padding:12px 16px; }
[data-testid="stMetricValue"] { font-weight:600; font-size:30px; }
@media (max-width: 640px) {
  .hero { margin-bottom:24px; padding-bottom:22px; } .hero .headline { font-size:30px; }
  .tiles { position:static; margin-top:18px; grid-template-columns:repeat(2, 1fr); }
  .tile .v { font-size:16px; }
}
.stButton button, .stDownloadButton button { border-radius:10px; font-weight:500; min-height:44px;
  border:1px solid #717d8c; color:var(--ink); background:#fff; }
.stButton button[kind="primary"] { background:var(--brand); border-color:var(--brand); color:#fff; }
.stButton button[kind="primary"]:hover { background:var(--brand-hover); border-color:var(--brand-hover); }
.stButton button:hover { border-color:var(--brand); color:var(--brand); background:var(--brand-tint); }
.stButton button { transition: background .15s ease, border-color .15s ease, color .15s ease,
  transform .1s ease-out; }
.stButton button:active { transform: scale(0.96); }
.stButton button[kind="primary"] p, .stButton button[kind="primary"]:hover p { color:#fff; }
[data-testid="stExpander"] details { background:#fff; border:1px solid var(--line); border-radius:12px; }
textarea, input { border-radius:8px !important; }
[data-testid="stAlert"] { border-radius:12px; }
</style>
"""


def section_title(text: str) -> None:
    """Section heading in the brand style: a short accent bar beside the title."""
    st.markdown(f'<div class="sec"><span class="bar"></span><b>{esc(text)}</b></div>', unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape(str(value))


def badge(text: str, state: str | None = None, big: bool = False) -> str:
    cls = "badge big" if big else "badge"
    return f'<span class="{cls}" style="{fmt.tone(fmt.state_colour(state or text))}">{esc(text)}</span>'


def row(body: str, state: str, colour: str | None = None) -> str:
    """A result line: a dot in the state's colour, then the text."""
    dot = colour or fmt.state_colour(state)
    return f'<div class="row"><span class="dot" style="background:{dot}"></span><div>{body}</div></div>'


def state_icon(state: str) -> str:
    return (
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" '
        f'stroke-linecap="round" stroke-linejoin="round"><path d="{STATE_PATH[state]}"/></svg>'
    )


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


@st.cache_resource
def boot_runs() -> dict:
    """What the demo invoices already did on this server since it started, shared by every visitor.

    The ledger takes each invoice once per start (a second try is the registry's duplicate block, by design),
    so a second visitor, or a reload, is shown the run that did it instead of posting the same PDF again.
    views: case -> view model. repaid: case -> the TX-5 row after Buyer paid."""
    return {"views": {}, "repaid": {}}


def is_duplicate_block(view: dict) -> bool:
    return bool((view.get("registry") or {}).get("duplicate"))


def run_file(content: bytes, name: str, case: str | None = None) -> str | None:
    """POST one invoice to /flow/run and put the result on screen. Returns a readable error, or None."""
    try:
        raw = orch.Orchestrator().run_flow(content, name)
        view = orch.to_view(raw, load_fixture("happy"))
    except orch.ServiceError as exc:
        return f"The flow stopped with an error: {exc.plain}."
    except (orch.Unavailable, orch.Unsupported, ValueError) as exc:
        return f"Orchestrator unavailable ({exc})."
    st.session_state.view = view
    st.session_state.update(paid=False, approved=False, notice=None, extra_tx=[], case=case or name)
    if case in CASE_KEYS and (case == "duplicate" or not is_duplicate_block(view)):
        boot_runs()["views"].setdefault(case, dict(view))  # the first run of a case is the one everyone sees
    return None


def show_earlier_run(case: str) -> None:
    """The case already ran on this server (this visit or another): show that run, with its Buyer paid row."""
    runs = boot_runs()
    repaid = runs["repaid"].get(case)
    st.session_state.view = {**runs["views"][case], "replayed": True}
    st.session_state.update(
        paid=bool(repaid), approved=False, notice=None, extra_tx=[repaid] if repaid else [], case=case
    )


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
    if case in boot_runs()["views"]:
        show_earlier_run(case)
        return
    if case == "duplicate" and "happy" not in boot_runs()["views"]:
        run_file(DEMO_INVOICE.read_bytes(), DEMO_INVOICE.name, "happy")  # something to be a duplicate of
    error = run_file((DEMO_DIR / filename).read_bytes(), filename, case)
    if error and (FIXTURES / "runs" / f"{case}.json").exists():
        show_saved_run(case, f"{error} Showing the saved run of this case instead.")
    elif error:
        st.session_state.notice = error
    elif case != "duplicate" and is_duplicate_block(load_view()):
        if case in boot_runs()["views"]:  # another visitor's click finished first
            show_earlier_run(case)
        else:
            st.session_state.notice = (
                "The registry already holds this invoice: it was financed on this server before this screen "
                "recorded it, so it cannot be financed twice. Restart the service for a clean run."
            )


def run_all() -> None:
    """Judge mode: every available case in order (Happy first, so Duplicate has something to repeat)."""
    board = []
    for case, label, filename, _ in [c for c in DEMO_CASES if case_available(c[0], c[2])]:
        run_case(case, filename)  # a case that already ran on this server is shown, not posted again
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
                    "earlier": False,
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
                "earlier": bool(view.get("replayed")),
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
    summary = f"Judge mode: {len(board)} invoices, {funded} funded, {held} sent to a person, "
    summary += f"{len(board) - funded - held} stopped."
    if funded == 1 and board[0]["case"] == "happy" and board[0]["state"] == story.DONE:
        summary += " Only one invoice moved money; every forged one was held or stopped."
    st.markdown(f'<div class="tally">{esc(summary)}</div>', unsafe_allow_html=True)
    for r in board:
        colour = story.STATE_COLOUR[r["state"]]
        tag = " (saved demo)" if r["saved"] else " (run earlier)" if r.get("earlier") else ""
        left, right = st.columns([6, 1], vertical_alignment="center")
        left.markdown(
            row(
                f'<b>{esc(r["label"])}</b> · <span class="chip" style="{fmt.tone(colour)}">'
                f'{esc(r["headline"] + tag)}</span><br><span class="why">{esc(r["sentence"])}</span>',
                "",
                colour,
            ),
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
            if col.button(label, key=f"case_{case}", width="stretch"):
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
        "The ledger registers each demo invoice once per server start. Click it again, or open this page "
        "elsewhere, and you see that run again with its real transaction hashes."
    )
    with st.expander("Or upload your own invoice"):
        upload = st.file_uploader("Invoice file", key="upload")
        if upload and st.button("Run flow with this file"):
            error = run_file(upload.getvalue(), upload.name)
            if error:
                st.session_state.notice = f"{error} The screen still shows the previous result."
            st.rerun()


def init_state() -> None:
    defaults = {
        "attacks": [],
        "paid": False,
        "approved": False,
        "compiled_mandate": None,
        "notice": None,
        "extra_tx": [],
        "case": None,
        "scoreboard": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def page_head(title: str, view: dict, sub: str | None = None) -> None:
    """A page's title and a line under it: by default, the invoice it is about. Every page but Home."""
    inv = view.get("ocr") or {}
    sub = sub or (
        f"Invoice {inv.get('invoice_no', '-')} · {(inv.get('supplier') or {}).get('name') or '-'} → "
        f"{(inv.get('buyer') or {}).get('name') or '-'}"
    )
    head = f'<div class="head"><h1>{esc(title)}</h1><div class="sub">{esc(sub)}</div></div>'
    st.markdown(head, unsafe_allow_html=True)


LEDGER_NAMES = {"fisco": "FISCO BCOS", "mock": "mock ledger"}


def ledger_pill(view: dict) -> str:
    """The ledger the run used; before any live run the saved demo's is not shown as if it were this one's."""
    chain = (view.get("wallet") or {}).get("chain")
    name = LEDGER_NAMES.get(chain, chain or "unknown")
    if view.get("source") == "orchestrator":
        return f"Ledger: {name}"
    if live() and view.get("source") == "fixtures":
        return "Ledger: shown after the first run"
    return f"Ledger: {name} (saved)"


def hero(view: dict) -> None:
    inv, d = view.get("ocr") or {}, view.get("policy") or {}
    owner = (inv.get("supplier") or {}).get("name") or "your company"
    amount = fmt.thb(inv.get("amount"), inv.get("currency", "THB")) if inv.get("amount") else "-"
    tiles = [
        ("Advance rate", fmt.pct(d["advance_rate"], 0) if d.get("advance_rate") else "-", True),
        ("Advance limit", fmt.thb(d["limit"]) if d.get("limit") else "-", False),
        ("Cost", f"{fmt.pct(d['apr'])} APR" if d.get("apr") else "-", False),
    ]
    state = story.verdict(view, st.session_state.paid)[0]
    decided = {"approve": "Approved", "review": "Sent to a person", "reject": "Rejected"}
    tile_html = "".join(
        f'<div class="tile"><div class="k">{esc(k)}</div>'
        f'<div class="v{" on" if on else ""}">{esc(v)}</div></div>'
        for k, v, on in tiles
    )
    label = decided.get(d.get("decision"), "Stopped")
    tile_html += (
        '<div class="tile"><div class="k">Decision</div>'
        f'<span class="chip" style="{fmt.tone(story.STATE_COLOUR[state])}">{esc(label)}</span></div>'
    )
    st.markdown(
        '<div class="hero"><div class="top"><div class="mark">R</div>'
        '<div><div class="name">ReceivableOS</div>'
        '<div class="tag">Invoice financing for Thai SMEs</div>'
        f'</div><div class="spacer"></div><span class="pill">{esc(ledger_pill(view))}</span></div>'
        '<div class="body"><div class="pitch">'
        '<div class="headline">Write the rule once. Your invoices fund themselves.</div>'
        '<div class="lede">An AI agent reads, prices and draws each invoice on-chain, but only inside the '
        "rule you signed. Code checks every step and the ledger records it.</div></div>"
        f'<div class="case"><div class="greet">Latest case from {esc(owner)}</div>'
        f'<div class="amt">{esc(amount)}</div>'
        f'<div class="sub">Invoice <span class="nw">{esc(inv.get("invoice_no", "-"))}</span> · '
        f"billed to {esc((inv.get('buyer') or {}).get('name') or '-')}</div></div></div>"
        f'<div class="tiles">{tile_html}</div></div>',
        unsafe_allow_html=True,
    )


def status_banner(view: dict) -> None:
    """Says on every page whether this is a live run, a saved run or fixtures."""
    if st.session_state.notice:
        st.warning(st.session_state.notice)
    if view.get("source") == "saved":
        label = {c[0]: c[1] for c in DEMO_CASES}.get(st.session_state.case, st.session_state.case)
        st.info(
            f"SAVED RUN: {label}, recorded from the live stack on the mock ledger. Nothing was called now."
        )
    elif view.get("source") == "fixtures" and live():
        st.info("SAVED DEMO: nothing has run live yet. Run an invoice below to call the live flow.")
    elif view.get("source") == "fixtures":
        st.info("FIXTURE MODE: saved responses, no backend called.")
    else:
        label = {c[0]: c[1] for c in DEMO_CASES}.get(st.session_state.case, st.session_state.case)
        if view.get("replayed"):
            st.success(
                f"LIVE, run earlier on this server: {label}. The ledger registers each demo invoice once per "
                f"server start, so this is the run that did it, with its real transaction hashes · "
                f"flow state {view.get('state')}"
            )
        else:
            st.success(f"LIVE: {label} · flow state {view.get('state')}")


def section_flow(view: dict) -> None:
    """Where the invoice got to, in one line a judge can read from the back of the room."""
    state, headline, sentence = story.verdict(view, st.session_state.paid)
    if view.get("source") in ("fixtures", "saved"):
        headline += " (saved demo)"  # never let a saved result read as this run's
    st.markdown(
        f'<div class="verdict" style="{fmt.tone(story.STATE_COLOUR[state])}"><b>{esc(headline)}</b>'
        f"{esc(sentence)}</div>",
        unsafe_allow_html=True,
    )
    cards = []
    for n, s in enumerate(story.steps(view, st.session_state.paid), 1):
        colour = story.STATE_COLOUR[s["state"]]
        cards.append(
            f'<div class="step"><span class="i" style="{fmt.tone(colour)}">'
            f'{state_icon(s["state"])}</span><span class="n">{n}. {esc(s["name"])}</span>'
            f'<div class="d">{esc(s["detail"])}</div></div>'
        )
    st.markdown(f'<div class="steps">{"".join(cards)}</div>', unsafe_allow_html=True)


def section_mandate(view: dict) -> None:
    text = st.text_area("The SME's rule, in plain language", view["mandate_text"], height=80)
    if st.button("Compile"):
        if live():
            try:
                st.session_state.compiled_mandate = orch.Orchestrator().compile_mandate(text)
            except orch.Refused as exc:
                st.error(f"{exc.plain}. Nothing was compiled; the rule below is unchanged.")
            except (orch.Unavailable, orch.Unsupported) as exc:
                st.warning(f"Compile not available from the orchestrator ({exc}); showing the saved mandate.")
        elif text.strip() != view["mandate_text"].strip():
            st.warning("Compiling new wording needs the orchestrator. Showing the saved demo mandate.")
    envelope = st.session_state.compiled_mandate
    if envelope:
        st.caption(
            "Compiled now by the policy service. This shows what the sentence turns into; "
            "the demo wallet keeps running on its own demo mandate."
        )
    else:
        envelope = view["mandate"]
        if live() and (view.get("source") == "fixtures" or "mandate" in view.get("from_fixture", [])):
            st.caption(
                "Saved: the demo rule as it compiled earlier. Press Compile to run it through policy-ai now."
            )
        else:
            fixture_label(view, "mandate")
    mandate = envelope["mandate"]
    cells = []
    for key, label, kind in MANDATE_FIELDS:
        value = mandate.get(key)
        shown = (
            fmt.pct(value, 0)
            if kind == "pct"
            else fmt.thb(value)
            if kind == "thb"
            else esc(value or "-")[:10]
        )
        source = fmt.field_source(envelope, key)
        colour = fmt.GREY if source == "default" else fmt.GREEN
        origin = f'<span style="color:{colour}">({"from text" if source == "text" else source})</span>'
        cells.append(row(f"<b>{label}</b>: {shown} {origin}", "", colour))
    st.markdown(f'<div class="grid">{"".join(cells)}</div>', unsafe_allow_html=True)
    with st.expander("Mandate JSON (wallet field names)"):
        st.json(envelope)


def section_invoice(view: dict) -> None:
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
        line_items(inv)
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
        fraud = min(max(float(inv["fraud_score"]), 0.0), 1.0)
        finding = fmt.RED if fraud >= MAX_FRAUD else fmt.AMBER  # one colour per finding, from the outcome
        st.markdown(
            f"Fraud score <b>{fraud:.2f}</b> against the {MAX_FRAUD:.2f} reject line"
            f'<div class="gauge"><div class="fill" style="width:{fraud * 100:.1f}%;'
            f'background:{fmt.GREEN if fraud < MAX_FRAUD else fmt.RED}"></div>'
            f'<div class="cap" style="left:{MAX_FRAUD * 100:.0f}%"></div></div>',
            unsafe_allow_html=True,
        )
        flags = [("injection", f) for f in inv.get("injection_flags", [])]
        flags += [("fraud", f) for f in inv.get("fraud_flags", [])]
        chips = "".join(
            f'<span class="chip" style="{fmt.tone(finding)}">{esc(k)}: {esc(f)}</span>' for k, f in flags
        )
        clean = f'<span class="chip" style="{fmt.tone(fmt.GREEN)}">no injection or fraud flags</span>'
        st.markdown(chips or clean, unsafe_allow_html=True)
        found = story.findings(inv)
        if found:
            lines = []
            for f in found:
                weight = f" <i>(+{esc(f['weight'])} fraud score)</i>" if f.get("weight") else ""
                detail = (
                    f"<br><span style='font-size:15px'>{esc(f['detail'])}</span>" if f.get("detail") else ""
                )
                headline = f["headline"][:1].upper() + f["headline"][1:]  # keep "QR", "PDF" as written
                lines.append(row(f"<b>{esc(headline)}</b>{weight}{detail}", "", finding))
            st.markdown("<b>What the document checks found</b>" + "".join(lines), unsafe_allow_html=True)
        st.markdown(
            f"doc_hash <code>{esc(fmt.short_hash(inv['doc_hash']))}</code><br>"
            f"fingerprint <code>{esc(fmt.short_hash(inv['invoice_fingerprint']))}</code>",
            unsafe_allow_html=True,
        )


def _num(value, places: int = 2) -> str:
    try:
        return f"{Decimal(str(value)):,.{places}f}"
    except (InvalidOperation, ValueError):
        return str(value or "-")


def line_items(inv: dict) -> None:
    """The invoice's own lines and what they add up to, next to the stated total. Text is escaped."""
    items = inv.get("line_items") or []
    if not items:
        return
    body = "".join(
        f"<tr><td>{esc(i.get('description'))}</td><td class='n'>{esc(_num(i.get('qty'), 0))}</td>"
        f"<td class='n'>{esc(_num(i.get('unit_price')))}</td>"
        f"<td class='n'>{esc(_num(i.get('total')))}</td></tr>"
        for i in items
    )
    st.markdown(
        '<table class="items"><tr><th>Line item</th><th class="n">Qty</th><th class="n">Unit price</th>'
        f'<th class="n">Total</th></tr>{body}</table>',
        unsafe_allow_html=True,
    )
    try:
        added = sum(Decimal(str(i.get("total"))) for i in items)
        amount = Decimal(str(inv["amount"]))
    except (InvalidOperation, ValueError):
        return

    def money(value: Decimal) -> str:
        return fmt.thb(value, inv["currency"])

    split = vat_split(inv)
    if split and split[0] == added:  # the document's own subtotal and tax: tax is not mistaken for inflation
        subtotal, tax = split
        sentence = f"Lines {money(subtotal)} + VAT {money(tax)} = {money(subtotal + tax)}"
        sentence += "." if subtotal + tax == amount else f", but the invoice total says {money(amount)}."
        st.caption(sentence)
    else:
        st.caption(f"Lines add up to {money(added)}; the invoice total is {money(amount)}.")


def vat_split(inv: dict) -> tuple[Decimal, Decimal] | None:
    """(subtotal, VAT) as OCR read them from the document, or None when either is missing."""
    evidence = inv.get("document_evidence") or {}
    found = []
    for name in ("subtotal", "tax_amount"):
        field = evidence.get(name) or {}
        if field.get("status") != "present":
            return None
        try:
            found.append(Decimal(str(field["value"])))
        except (InvalidOperation, ValueError, KeyError):
            return None
    return found[0], found[1]


def section_decision(view: dict) -> None:
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
    if d["decision"] != "approve":
        st.caption("Not approved: these are the terms the policy computed, not money paid.")
    deciding = ("HARD.", "KO.", "REVIEW.")  # the rules that decided it come first, model drivers last
    reasons = sorted(
        d["reasons"], key=lambda r: 0 if r.startswith(deciding) else 2 if r.startswith("MODEL.") else 1
    )
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
    section_title("Lender offers")
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
    if live() and view.get("source") == "fixtures":  # the saved demo's mock: hashes are not this ledger's
        none_yet = row("No transactions yet: run an invoice on the Home page.", "unknown")
        st.markdown(none_yet, unsafe_allow_html=True)
        return
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
    if live() and (st.session_state.get("view") or {}).get("source") == "orchestrator":
        case = st.session_state.case
        shared = boot_runs()["repaid"] if flag == "paid" and case in CASE_KEYS else {}
        try:
            if case in shared:  # another visit already recorded the payment; settling twice would be refused
                st.session_state.extra_tx.append(shared[case])
            else:
                tx = orch.action_row(call(orch.Orchestrator()), step, label)
                st.session_state.extra_tx.append(tx)
                if tx["status"] in ("executed", "settled"):
                    shared[case] = tx
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
    stopped = a["status"] in STOPPED_STATUSES
    label = a.get("label") or ""
    source = (
        badge("LIVE", "executed")
        if label == "live"
        else badge("SAVED", "unknown") + f" <i>({esc(label)})</i>"
        if label
        else ""
    )
    deciding = [c for c in a.get("policy_reasons", []) if c.startswith(("HARD.", "KO.", "REVIEW."))]
    reasons = [story.plain(deciding[0]) if deciding else None, story.plain(a.get("block_reason"))]
    why = "; ".join(dict.fromkeys(r for r in reasons if r))
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
        a["status"],
        BRAND if stopped else None,
    )


def section_attacks() -> None:
    if st.button("Run all five attacks", key="attack_all", type="primary"):
        st.session_state.attacks += [run_attack(case) for case in ATTACKS]
    for start in range(0, len(ATTACKS), 3):
        cols = st.columns(3)
        for col, case in zip(cols, ATTACKS[start : start + 3], strict=False):
            if col.button(ATTACK_LABELS[case], key=f"attack_{case}", width="stretch"):
                st.session_state.attacks.append(run_attack(case))
    done = st.session_state.attacks
    if not done:
        return
    # Live, only what the wallet really answered counts; a saved row (orchestrator down) is not tallied.
    counted = [a for a in done if a.get("label") == "live"] if live() else done
    held = sum(a["status"] in STOPPED_STATUSES for a in counted)
    if counted:
        tally = f"{held} of {len(counted)} attacks blocked"
        tally += ". No money moved." if held == len(counted) else f". {len(counted) - held} got through."
    else:
        tally = "No attack ran live, so nothing is counted: the rows below are saved."
    if counted and len(counted) < len(done):
        tally += f" {len(done) - len(counted)} saved row(s) below are not counted."
    st.markdown(f'<div class="tally">{esc(tally)}</div>', unsafe_allow_html=True)
    for a in done:
        st.markdown(attack_row_html(a), unsafe_allow_html=True)
    if st.button("Clear results", key="attack_clear"):
        st.session_state.attacks = []
        st.rerun()


def footer(view: dict) -> None:
    d = view["policy"] or {}
    audit = (view.get("wallet") or {}).get("audit_ref", "-")
    st.divider()
    st.caption(
        f"policy_version {d.get('policy_version', '-')} · model_version {d.get('model_version', '-')} · "
        f"decision_hash {fmt.short_hash(d.get('decision_hash'))} · audit {audit}"
    )


def page_home() -> None:
    view = load_view()
    hero(view)
    run_controls()
    section_title("Where this invoice got to")
    section_flow(view)
    section_scoreboard()
    section_title("Look closer")
    for col, (path, title, icon, blurb) in zip(st.columns(len(PAGES) - 1), PAGES[1:], strict=True):
        col.page_link(path, label=title, icon=icon)
        col.caption(blurb)


def page_invoice() -> None:
    page_head("Invoice", load_view())
    section_invoice(load_view())


def page_decision() -> None:
    page_head("Credit decision", load_view())
    section_decision(load_view())
    section_offers(load_view())


def page_rule() -> None:
    page_head("My rule", load_view())
    section_mandate(load_view())


def page_ledger() -> None:
    page_head("Ledger", load_view())
    section_chain(load_view())


def page_security() -> None:
    sub = "Each button tries to make the agent move money it should not. Every one must come back BLOCKED."
    page_head("Security tests", load_view(), sub)
    section_attacks()


def main() -> None:
    st.set_page_config(page_title="ReceivableOS", page_icon="◆", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    pages = [st.Page(path, title=title, icon=icon) for path, title, icon, _ in PAGES]  # the first is Home
    nav = st.navigation(pages, position="top")
    status_banner(load_view())
    nav.run()
    footer(load_view())


if __name__ == "__main__":  # streamlit runs the script as __main__; tests import it without rendering
    main()
