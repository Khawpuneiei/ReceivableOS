# ui/web: ReceivableOS for SME owners

The owner-facing web app, in TypeScript (React 19 + Vite). It follows the SME-owner design canvas: seven
screens behind a left sidebar (a bottom tab bar on a phone): **Home**, **Get cash** (upload or a sample invoice,
then the checks), the **invoice result** (what you got, the money step by step, the lender quotes, how we
checked it, receipts), **Invoices**, **Needs you**, **My rule** and **Money & activity** (every baht, every
blocked attempt, the six protection tests, a CSV of receipts). Owner: Policy AI engineer. Port 3001; the
Streamlit demo in `ui/` keeps port 3000 and stays the harness for testing the OCR, LLM and chain calls.

## Run

```bash
cd ui/web
npm ci
npm run dev                 # sample mode on http://localhost:3001, no backend needed
```

**Sample mode** (`UI_MODE=fixtures`, the default) replays responses recorded from the live stack in
`ui/fixtures/runs/` and `ui/fixtures/a1.json`…`a6.json`. A banner on every page says so. Uploading any file shows
the clean invoice's recorded run; the demo file names (`02_injected.pdf` and so on) pick their own run, and the
clean invoice a second time is refused as a duplicate, like the live registry does.

**Live mode** sends every call to the orchestrator:

```bash
UI_MODE=live ORCHESTRATOR_URL=http://localhost:8000 npm run dev
```

The browser only ever calls `/api/...`. The Vite dev server (and `npm run preview` after `npm run build`)
forwards `/api` to `ORCHESTRATOR_URL` and adds `X-Orchestrator-Token` from `ORCHESTRATOR_TOKEN` on the server
side, so the token never reaches the page or the bundle. Both read the repo root `.env` and the shell.

| Owner action | Orchestrator route | Today |
|---|---|---|
| Get cash (file or sample PDF from `data/invoices/demo/`) | `POST /flow/run` | served |
| Demo: the buyer pays today | `POST /flow/repay` (form `invoice_id`) | served |
| Run the six protection tests | `POST /flow/attack/{A1..A6}` | A1–A5 served; A6 shows the recorded result, labelled |
| Save and sign my rule | `POST /flow/mandate/compile` | not served: the app says so and keeps the signed rule |
| Approve a draw above the ask-me limit | `POST /flow/confirm/{tx_id}` | not served: the app says so and pays nothing |

The orchestrator draws as soon as an invoice passes inside the owner's rule, so the result page reports money
already received rather than asking the owner to accept. Only a draw at or above the ask-me limit waits for
the owner (the wallet's `pending_approval`).

## Test

```bash
npm run typecheck && npm test && npm run build
```

`tests/` covers the money maths (decimal strings, never floats), every recorded run's status and wording, the
activity feed and CSV export, the live client's error handling, the token staying server side, and the main
owner flows rendered end to end in sample mode.
