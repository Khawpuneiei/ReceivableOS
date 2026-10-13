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

## Live mode (`UI_MODE=live`)

```bash
UI_MODE=live ORCHESTRATOR_URL=http://localhost:8000 streamlit run ui/app.py --server.port 3000
```

The screen talks **only** to the orchestrator, through `ui/client.py`. Four one-click cases post the PDFs in `data/invoices/demo/`: Happy, Injected instructions, Inflated amount and Duplicate (re-saved PDF); Duplicate runs Happy first when this session hasn't, so there is something to duplicate. Any other file goes through "Or upload your own invoice". Each run
posts to `POST /flow/run`, and `client.to_view` maps the response onto the view model. It reads both today's
flat `{mandate_id, ocr, registry, policy, wallet, outcome}` and the brief's `{flow_id, state, steps: [...]}`.
Nothing crashes when the orchestrator is missing something:

| Need | Orchestrator route the UI calls | Today | What the screen does |
|---|---|---|---|
| Run the flow | `POST /flow/run` (file, `mandate_id`) | served | live OCR, policy and wallet results; a duplicate shows STOPPED with a red registry row |
| Compiled mandate | `POST /flow/mandate/compile` `{text}` | missing | saved mandate, labelled FIXTURE |
| Ledger timeline | `register` (TX-1), `approve` (TX-2), `wallet` (TX-4) in `/flow/run` | served | one row per wallet call that ran; a duplicate shows the wallet's own red TX-1 |
| Lender quotes | `offers` in `/flow/run` | served | live quotes; "Not reached" when the flow stopped at review, reject or a duplicate |
| Human approval | `POST /flow/confirm/{tx_id}` | missing | amber notice; the button is marked done |
| Buyer paid | `POST /flow/repay` (JSON `{flow_id, amount_paid}` when there is a `flow_id`, else form `invoice_id`) | stub reply | shows the stub's status as a grey TX-5 row |
| Attacks A1–A6 | `POST /flow/attack/{case}` | missing | saved attack row, labelled "fixture: orchestrator has no attack route" |
| Audit link | `audit_ref` from the wallet result | served (stub ref) | shown in the footer |

A service that fails behind the orchestrator is named in plain words ("the OCR service refused the request (HTTP 415): …"). [Buyer paid] appears only after a draw executed. An unreachable orchestrator gives an amber "Orchestrator unavailable … showing fixtures" banner and the fixture
screen. A live attack response that was **not** stopped is shown with its real status, never relabelled BLOCKED.

## What is on screen, and where the numbers come from

| Section | Content | Source in fixture mode |
|---|---|---|
| Flow strip | a coloured verdict ("Funded inside the rules", "Sent to a person", "Rejected", "Stopped: duplicate invoice") with one sentence built from the reason codes, then six steps (Upload, Read, Registry, Policy, Wallet, Settle) each green / amber / red / grey with a short detail; attack rows add a plain "Why:" line | `ui/story.py` over the same view model; unknown codes get no made-up text |
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

Projector and laptop: buttons are navy (`primaryColor` in `ui/.streamlit/config.toml`) so green, amber and red mean only states; the Deploy toolbar is hidden; OCR confidence is a green / amber bar with the 80% minimum marked; the fee shows the APR as the headline and the per-30-day rate under it; known reason codes get plain words next to the code; the mandate is a two-column grid; the step strip fits six steps from 1024 px. Design rules: state colours only (green executed / approve, amber review / pending, red blocked / reject), body
text 18 px, money with thousands separators, rates in both the per-30-day and APR forms. Invoice text is untrusted
and is HTML-escaped before display. No personal data beyond company names.

## Test

```bash
python3 -m pytest ui -q
ruff check ui
```

- `tests/test_story.py`: the step states and verdict sentence for funded, review, reject and duplicate.
- `tests/test_format.py`: THB and rate formatting, state colours, short hashes, mandate field sources.
- `tests/test_app_smoke.py`: Streamlit's `AppTest` renders the screen in fixture mode with sockets blocked,
  clicks A1–A6 and [Buyer paid], and checks that the rows appear; in live mode with no orchestrator it checks
  the amber banner and the labelled fixture fallback.
- `tests/test_client.py`: the adapter on both response shapes, a duplicate that stops before policy, 404/405 as
  unsupported, 5xx and refused connections as unavailable, the repay body, and attack rows.
