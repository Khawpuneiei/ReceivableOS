# 08 · Code walkthrough

A guided read of the code, for someone who has to explain it. It follows one invoice through the files, then the
guard, CI/CD, Docker and state. It does not repeat the *why*: that is in `01-architecture.md` (trust model,
contracts), `03-agent-wallet.md` (guard layers, attack numbers) and `06-controls-and-compliance.md`.

Every reference is `path:line` on `main` as of 6 Nov 2026. Line numbers drift; search for the function name if
one is off. Anything marked **not verified** was read but not run or traced to the end.

## 1. One invoice, end to end

Entry point: `services/orchestrator/app/main.py:121` `flow_run`. Every hop is an `httpx` POST through `_post`
(`main.py:77`). The orchestrator returns a `steps` dict with every intermediate result and an `outcome` string,
and stops early at the first hop that does not succeed.

| # | Hop | Code | Request → response model | Fails how, and what happens |
|---|---|---|---|---|
| 1 | Caller → orchestrator | `main.py:121` (`check_caller`, `main.py:46`) | multipart `file`, form `mandate_id` (default `mdt_001`) | No or wrong `X-Orchestrator-Token` → 403 |
| 2 | → ocr-ai `POST /ocr/extract` | `main.py:127`; served by `services/ocr-ai/app/main.py:112` → `app/pipeline.py:337` `extract_invoice` | file → `OcrExtractResponse` (`pipeline.py:45`), a subclass of `shared/schemas.py:31` `ExtractedInvoice` with optional extras | 413/415/422 keep their status (`UPLOAD_FAULTS`, `main.py:74`); anything else becomes 502 |
| 3 | → agent-wallet `POST /wallet/register` (TX-1, the duplicate check) | `main.py:136`; served by `services/agent-wallet/app/main.py:138` → `app/wallet/lifecycle.py:277` `_register` → `ledger.register` | `WalletRegisterRequest` (`schemas.py:111`) → `WalletResult` (`schemas.py:180`) | `status != executed` → `outcome = "blocked: DuplicateReceivable"` (or the other block reason), flow stops (`main.py:153`) |
| 4 | → policy-ai `POST /policy/decide` | `main.py:162`; served by `services/policy-ai/app/main.py:38` → `app/decision.py:76` `decide` | `PolicyRequest` (`schemas.py:58`) → `PolicyDecision` (`schemas.py:71`), extended as `PolicyDecisionExt` in `services/policy-ai/app/schemas.py` | 422 on a bad request → 502 at the orchestrator. `decision != approve` → `outcome = "review: wallet not called"`, flow stops (`main.py:165`) |
| 5 | → agent-wallet `POST /wallet/approve` (TX-2, risk oracle) | `main.py:170`; `agent-wallet/app/main.py:145` → `lifecycle.py:317` `_approve` | `WalletApproveRequest` (`schemas.py:124`) → `WalletResult` | Hash mismatch, not `approve`, or PD above the mandate → `blocked`, flow stops (`main.py:187`) |
| 6 | Lender quote (in-process) | `main.py:191` `select_quote` (`main.py:91`), quotes from `data/agent/lender_quotes.json` | decision → chosen quote + all offers | No quote within the approved APR → `outcome = "blocked: no lender quote…"` |
| 7 | → agent-wallet `POST /wallet/execute` (TX-4, the draw) | `main.py:199`; `agent-wallet/app/main.py:131` → `lifecycle.py:367` `_execute` → `guard/pipeline.py:35` `check_draw` → `ledger.execute` | `WalletRequest` (`schemas.py:92`) → `WalletResult` | Any failed guard check → `blocked` with `block_reason` and `checks`; the ledger is not called. On-chain revert → `blocked` with an `L5` check |
| 8 | Buyer pays: `POST /flow/repay` (TX-5) | `main.py:252` → `/wallet/settle` → `lifecycle.py:504` `_settle` | form `invoice_id`, `amount_paid` → `WalletResult` | Unknown `invoice_id` → 404; `amount_paid` ≤ 0, above face or > 2 decimals → 422 (`parse_amount_paid`, `main.py:54`) |

What happens inside each service on the happy path:

- **ocr-ai.** `read_upload` (`services/ocr-ai/app/ingest.py:39`) caps the upload at 10 MB and checks magic bytes
  against the content type (`detect_format`, `ingest.py:61`). Parsing runs in a child process with a stripped
  environment and a timeout (`run_worker`, `ingest.py:75`), so a hostile PDF never sees the HMAC keys.
  `extract` (`pipeline.py:60`) builds the fields; injection detection runs over every text span, hidden text,
  split rows, metadata and QR payloads (`app/extract.py:236-275`). `compatible_invoice` (`pipeline.py:152`)
  refuses the invoice (422) unless every critical field is present, and computes `invoice_fingerprint`
  (`app/fingerprint.py:33` `legacy_fingerprint`: HMAC-SHA256 over
  `v1|supplier|buyer|invoice_no|amount|currency|issue_date`). `observe` (`pipeline.py:206`) writes the
  observation to SQLite and turns earlier sightings and graph patterns into fraud findings; `fraud.score`
  (`app/fraud.py:129`) combines their weights as `1 - Π(1 - w)`. The `invoice_id` the rest of the flow uses is
  OCR's observation id (`pipeline.py:354`).
- **Registry.** The mock ledger's `register` (`services/agent-wallet/ledger/mock.py:142`) reverts
  `DuplicateReceivable` if the fingerprint is already known, the same string as
  `contracts/src/ReceivableRegistry.sol:74`. A re-saved PDF has a new `doc_hash` but the same fingerprint, so it
  is caught here.
- **policy-ai.** No LLM on this path (`services/policy-ai/app/main.py:3`). `decide` (`decision.py:76`) applies
  the default mandate if the request has none, runs the YAML rule set
  (`services/policy-ai/rules/policy.v1.yaml`) and the PD model through `engine.evaluate` (`engine.py:469`),
  merges outcomes with "most severe wins" (`engine.py:476`), and signs the result with `decision_hash`
  (`app/hashing.py:35`: keccak256 of the canonical JSON of the shared-contract fields).
- **agent-wallet.** See section 3.

## 2. One route in depth: `POST /flow/run`

- **Auth.** `check_caller` (`orchestrator/app/main.py:46`) fails closed: if `ORCHESTRATOR_TOKEN` is empty, every
  call is refused. The comparison is `hmac.compare_digest` (constant time). The token matters because this
  service holds the wallet's agent and risk-oracle tokens (`main.py:31-33`). The UI sends it from env
  (`ui/client.py:76`), as does `run_demo.py:18`.
- **Validation.** FastAPI checks that `file` exists and `mandate_id` is a string. The orchestrator does **not**
  size-check or type-check the upload itself; it forwards the bytes and lets ocr-ai refuse them. Responses from
  the services are read as plain dicts (`r.json()`, `main.py:88`), not re-validated against `shared/schemas.py`;
  the wallet validates its own inputs with Pydantic.
- **Timeouts.** One `httpx.AsyncClient(timeout=60)` per request (`main.py:70`), so each hop gets up to 60 s.
  There are no retries. OCR allows only two documents in flight (`ocr-ai/app/main.py:21`) and answers 429 to a
  third, which the orchestrator turns into 502.
- **Error handling.** `_post` (`main.py:77`) maps a network error to `502 "<url> unreachable"` and any 4xx/5xx
  to `502 "<url> answered <code>: <first 300 chars>"`, except ocr-ai's 413/415/422 which are the caller's fault
  and keep their status. A business "no" (duplicate, review, reject, guard block) is **not** an HTTP error: it
  is a 200 with `outcome` set to the reason, which is what the demo screen shows.
- **Idempotency.** Each wallet call carries `"<invoice_id>:register|approve|draw|settle"`. The wallet's `_run`
  (`agent-wallet/app/wallet/lifecycle.py:184`) returns the stored result for a repeated key and sends nothing to
  the ledger.
- **Memory.** On a successful register, `_flows[invoice_id]` (`main.py:43`, `main.py:156`) keeps what
  `/flow/repay` needs. It is a process dict, so a restart forgets it and `/flow/repay` then answers 404.

## 3. The guard: "LLM output never becomes a transaction directly"

Where an LLM can appear at all: OCR's optional hosted/Qwen readers (`ocr-ai/app/pipeline.py:91-142`), policy-ai's
mandate compiler and explainer (`policy-ai/app/mandate.py:512`, `explain.py:183`). In each case the LLM only
*proposes* values that deterministic code compares or validates; a disagreement adds a review reason, it never
overrides the parsed value. `/policy/decide` imports no LLM client. With `LLM_PROVIDER` unset (the CI and Render
setting) no LLM is called anywhere.

The checks between any text and the money, in order:

1. **OCR flags, policy hard rules.** `injection_flags` non-empty → `review`; `fraud_score ≥ 0.30` → `reject`;
   `confidence < 0.80` → `review` (`policy-ai/rules/policy.v1.yaml:15-17`, predicates at
   `policy-ai/app/engine.py:139-160`). A non-approve decision stops the orchestrator before the wallet
   (`orchestrator/app/main.py:165`).
2. **Role tokens.** Each wallet route checks its own header with `hmac.compare_digest`
   (`agent-wallet/app/main.py:109`): agent token for register/execute/settle, risk-oracle token for approve,
   approver token for confirm, owner token for mandate and unpause. The agent cannot approve its own draw.
3. **TX-2 binding.** `_approve` (`lifecycle.py:317`) recomputes the decision hash and requires it, the limit and
   the fee to match, the decision to be `approve`, and PD to be within the mandate. Only then is the approval
   written to the registry.
4. **Off-chain guard L0-L4.** `check_draw` (`agent-wallet/app/guard/pipeline.py:35`) runs every check and
   reports all of them: L0 currency; L1 approved, not stale, hash equals the one approved at TX-2
   (`pipeline.py:51-63`); L2 injection scan of every string in the request plus a canary
   (`pipeline.py:65-73`, scanner in `guard/injection.py:353`); L3 registered, payee is the registered seller,
   KYC, not drawn, not paused, mandate dates, APR ≤ min(mandate, approval), per-tx cap, 24 h cap, PD, advance
   rate, amount ≤ limit (`pipeline.py:75-103`); L4 amount at or above `human_review_above` waits for the
   approver (`pipeline.py:105`). Any failure → `_blocked`, and the ledger is never called
   (`lifecycle.py:407`).
5. **Payees by id only.** A payee is a key into `config/payees.json` (`app/models.py:176` `Payee`,
   `models.py:196` `load_payees`); a raw address from text resolves to nothing and fails `PayeeNotAllowed`.
   Calldata is built only from typed intents (`models.py:201`).
6. **Fail-closed APR.** `_execute` takes the highest APR any source claims (`lifecycle.py:373-378`).
7. **Chain (L5).** The contracts repeat the money checks: `AgentWallet.execute` calls `PolicyGuard.check` and
   `record` (`contracts/src/AgentWallet.sol:84-97`); `PolicyGuard._validate` checks target allowlist, expiry,
   per-tx cap, daily cap, APR (`PolicyGuard.sol:133-144`); `FinancingVault.draw` checks approved status, APR,
   limit, advance against face value, fees and liquidity (`FinancingVault.sol:65-84`). `ledger/mock.py:185-216`
   raises the same revert strings in the same order, so `CHAIN_MODE=mock` answers like FISCO.
8. **Audit chain.** Every write is appended to a hash-chained log (`app/audit/log.py:16` `_digest`, `verify` at
   `log.py:56`) holding ids, hashes, amounts and codes only.

The `DEMO_MODE=1` bypass (`skip_offchain_checks`, `lifecycle.py:400`) skips step 4 so the demo can show the chain
refusing on its own; without `DEMO_MODE` the route refuses the flag (`agent-wallet/app/main.py:134`).

## 4. CI and CD, job by job

`.github/workflows/ci.yml` runs on every pull request, on pushes to `main` and on manual dispatch, with no hosted
OCR or LLM (`ci.yml:19-24`).

| Job | Lines | What it does | Why |
|---|---|---|---|
| `lint` (ruff) | `ci.yml:27` | `ruff check .` and `ruff format --check .` with ruff 0.17.0 | One style, no review time spent on formatting |
| `test` (matrix) | `ci.yml:42` | `pytest` per folder: `shared`, the four services, `ui`; `fail-fast: false` | One red service does not hide another |
| `redteam` | `ci.yml:67` | Runs `services/agent-wallet/eval/redteam_summary.py`, then `git diff --exit-code` on `eval/REDTEAM.md` | Fails if any attack makes an unauthorized payment, or if the committed pitch numbers are stale |
| `e2e` | `ci.yml:96` | `scripts/ci_env.sh`, `scripts/stack.sh start`, the live matrix `test_e2e_live.py`, then `run_demo.py` with `grep` for `outcome   executed` and `settle    TX-5 executed` | The definition of done in `CLAUDE.md`: the four services run end to end on the mock ledger |

CI does not build the Docker image.

`.github/workflows/cd.yml` runs on pushes to `main` and on manual dispatch. One job (`cd.yml:20`): `docker compose
build`, `scripts/ci_env.sh`, `docker compose up -d --wait`, the same `run_demo.py` grep inside the orchestrator
container, the UI health URL, container logs, then publish to GHCR as `:<sha12>` and `:latest`. The publish step's
condition is `github.event_name == 'push' || github.ref == 'refs/heads/main'` (`cd.yml:43`), so a manual run on
another branch builds and smoke-tests but does not publish. `concurrency: cd-main` keeps two publishes from racing.

`.github/workflows/keepalive.yml` pinged the two Render judge demos every ten minutes so judges never met a cold
start. It exits immediately after 31 Oct 2026, so it is now a no-op that still gets scheduled.

## 5. Docker and compose

`deploy/Dockerfile` (multi-stage since the `build/multi-stage-dockerfile` PR):

- **builder** (`python:3.11-slim`): copies the five `requirements.txt` files first so the install layer is
  cached, then creates `/opt/venv --without-pip` and installs into it with the base image's pip.
- **runtime** (`python:3.11-slim`): adds user `app` (uid 10001) and `/state`, copies `/opt/venv` and `shared`,
  `data`, `services`, `ui`, runs as `app`. `PATH` starts with `/opt/venv/bin`, so `python`, `uvicorn` and
  `streamlit` need no path in compose or on Render.
- `.dockerignore` keeps `.env`, `.git`, `docs`, `pitch`, tests, the eval folder and key files out of the build
  context.

`docker-compose.yml` builds that one image as `receivableos:local` and picks the service by `command`:

- Every service reads `.env` (required) and gets the internal URLs and `CHAIN_MODE=mock` (`docker-compose.yml:9-17`).
- Health checks call `/health` (or Streamlit's `/_stcore/health`) with Python's `urllib`, every 5 s, 20 retries
  (`docker-compose.yml:29-33`), because the slim image has no `curl`.
- Start order: `ocr-ai`, `policy-ai`, `agent-wallet` start together; `orchestrator` waits for all three to be
  healthy (`docker-compose.yml:58`); `ui` waits for the orchestrator (`docker-compose.yml:74`).
- Ports bind to `127.0.0.1` only. The UI runs with `working_dir: /app/ui` so Streamlit finds `.streamlit/config.toml`.
- Render (`deploy/RENDER.md`) does not use compose: one container starts the four services on 127.0.0.1 in the
  background and Streamlit in the foreground on `$PORT`.

## 6. State: where each service keeps its data

| Service | State | Where | Survives |
|---|---|---|---|
| orchestrator | `_flows` (what `/flow/repay` needs) | process memory (`orchestrator/app/main.py:43`) | nothing |
| ocr-ai | observation history (duplicates, fraud graph) | SQLite at `OCR_STATE_PATH` (`ocr-ai/app/config.py:79`); compose sets `/state/ocr-state.sqlite`, default `services/ocr-ai/.state/observations.sqlite`; `scripts/stack.sh` deletes it on every start | a container restart, but not a recreate (no named volume) |
| ocr-ai | result cache for `GET /ocr/invoices/{id}` | memory, 500 entries, 15 min (`ocr-ai/app/main.py:22`) | nothing |
| policy-ai | none; rules, model and default mandate are read-only files in `rules/` and `model/` | | |
| agent-wallet | receivables, idempotency results, spends, holds | `Store` in memory (`app/wallet/store.py:44`) | nothing; on FISCO, startup re-reads the 24 h spend from the chain (`agent-wallet/app/main.py:98`) |
| agent-wallet | audit log | memory (`app/audit/log.py:21`), head anchored on chain after settlement | nothing in mock mode |
| agent-wallet | ledger | mock: memory (`ledger/mock.py`); fisco: the chain, receipts as JSON in `FISCO_RECEIPTS_DIR` | mock: nothing |
| ui | the current view | Streamlit `session_state` (`ui/app.py:308`) | the browser session |

This is why `RENDER.md` says to restart the demo before judges try the happy invoice: a second run of
`01_happy.pdf` is a duplicate.

## 7. The red-team eval

- **Cases.** JSONL files in `services/agent-wallet/eval/`: the seed set `cases.jsonl`, `dev_cases.jsonl`, five
  held-out sets and `approval_cases.jsonl` (list at `eval/redteam_summary.py:25`). Each line has `id`,
  `category` (prompt injection, tool-output injection, exfiltration, payee swap, cap and APR abuse, replay, …),
  `attack` true/false, the expected status and code, the endpoint, setup steps and a `patch` applied to a known
  good request. 216 attacks and 86 benign cases in total (`eval/REDTEAM.md`).
- **Harness.** `eval/run_eval.py` builds a fresh mock wallet per case with fixed tokens and a fixed clock
  (`run_eval.py:41-48`), runs the setup and sends the patched request through the real FastAPI app via `TestClient` (`run_eval.py:177`). `unauthorized_reasons`
  (`run_eval.py:365`) then reads what the *ledger* recorded, not the guard's verdict: money to a non-allowlisted
  address, above the per-tx or daily cap, paid twice, after expiry, above the limit or the advance ceiling, or
  at an APR or PD outside the mandate.
- **Summary.** `redteam_summary.py` runs every set twice (`row_for`, `redteam_summary.py:73`): full stack, and
  chain alone with `skip_offchain_checks`. It also counts what the L2 scanner alone flags. It writes
  `eval/REDTEAM.md` and exits 1 if the full stack let any unauthorized payment through (`redteam_summary.py:127`).
  The committed result: scanner alone 133/216, chain alone 53/216 stopped with 0 unauthorized, full stack 186/216
  stopped, 30 reached execute but inside the mandate, **0 unauthorized**, 84/86 benign completed.
- **In CI.** The `redteam` job runs it and then `git diff --exit-code eval/REDTEAM.md`, so a code change that
  shifts any number fails until the new file is committed.

Not verified: the eval runs only against the mock ledger. The FISCO receipts in `eval/fisco-receipts*` come from
separate scripted runs and were not re-run for this doc.
