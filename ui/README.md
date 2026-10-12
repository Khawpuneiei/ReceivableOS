# ui: ReceivableOS demo screen

One Streamlit screen for the 3-minute demo (brief section 12): **mandate → invoice → decision → offers →
on-chain → attacks**, with the policy and model versions, the decision hash and the audit reference in the footer.
Owner: Policy AI engineer. Port 3000.

## Run

```bash
python3 -m pip install -r ui/requirements.txt
cd ui && streamlit run app.py          # port 3000 and the 18 px light theme come from ui/.streamlit/config.toml
```

From the repo root, `streamlit run ui/app.py --server.port 3000` also works, with Streamlit's default theme
(Streamlit reads `.streamlit/config.toml` from the working directory).

`UI_MODE=fixtures` (the default) renders saved responses from `ui/fixtures/` and calls nothing, so the screen
works with no backend. A blue "FIXTURE MODE" banner says so on screen.

## What is on screen, and where the numbers come from

| Section | Content | Source in fixture mode |
|---|---|---|
| Header | title and ledger badge (`mock` / `fisco`, from the wallet result's `chain`) | `happy.json` → `wallet` |
| 1. Mandate | the SME's sentence, [Compile], the compiled mandate (green = from the text, grey = platform default) | real `compile_mandate` output for `services/policy-ai/fixtures/mandates/demo_thb.txt` |
| 2. Invoice | parties, number, dates, amount, OCR confidence bar, injection / fraud chips, short `doc_hash` and fingerprint | the scenario 1 invoice fixture |
| 3. Decision | APPROVE / REVIEW / REJECT badge, advance, limit, fee as "0.90% / 30 days (10.95% APR)", PD gauge against the mandate's 5% line, reasons with rule ids, a "Why?" expander with the model drivers and the rule trace | real `/policy/decide` response for scenario 1 (model `credit-lr-2026-10-10.2`) |
| 4. Offers | lender quotes; chosen row green, out-of-mandate rows red with the reason | hand-written from `docs/00-scope.md` (Lender A 70% at 10.95% APR, Lender B 65% at 9.13%) |
| 5. On-chain | TX-1, TX-2, TX-4 with status and short tx ref; [Approve] when the wallet returns `pending_approval`; [Buyer paid] adds TX-5 | hand-written in the `WalletResult` shape with `mock:0x…` refs |
| 6. Attacks | A1–A6 buttons; each adds a red BLOCKED row: who stopped it, the policy decision and codes, the revert reason, the tx ref | A1, A2 and A5 carry real policy decisions (scenarios 4, 5 and 7); revert reasons and refs are hand-written |

`python ui/build_fixtures.py` rebuilds every fixture from policy-ai's own fixtures, so the policy numbers on screen
change only when the policy service changes. Registry, quotes and wallet parts stand in for the orchestrator until
it serves them; they are labelled as fixtures and use mock ledger refs, never real-looking chain hashes.

Design rules: state colours only (green executed / approve, amber review / pending, red blocked / reject), body
text 18 px, money with thousands separators, rates in both the per-30-day and APR forms. Invoice text is untrusted
and is HTML-escaped before display. No personal data beyond company names.

## Test

```bash
python3 -m pytest ui -q
ruff check ui
```

- `tests/test_format.py`: THB and rate formatting, state colours, short hashes, mandate field sources.
- `tests/test_app_smoke.py`: Streamlit's `AppTest` renders the screen in fixture mode with sockets blocked,
  clicks A1–A6 and [Buyer paid], and checks that the rows appear.
