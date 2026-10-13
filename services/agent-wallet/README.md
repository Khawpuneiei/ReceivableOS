# agent-wallet

Owner: Agent AI engineer. The wallet holds the keys and moves tTHB, and it owns all the Solidity
([`contracts/`](contracts/README.md)). Design: [`docs/03-agent-wallet.md`](../../docs/03-agent-wallet.md).
Build brief for the service: [`CLAUDE.md`](CLAUDE.md). Request and response models: [`shared/schemas.py`](../../shared/schemas.py).

## Status

- **Mock ledger:** the money loop runs end to end over HTTP: register, approve, execute, settle. Guard L0–L4,
  the hash-chained audit log, and hold-for-approval work. `scripts/demo.py` runs against it.
- **FISCO BCOS 3.16.4:** a 4-node Air chain runs in Docker. The five contracts are deployed and wired, the wallet runs
  against them with `CHAIN_MODE=fisco`, and the demo's on-chain transactions are checked on chain. The records are in
  [`eval/fisco-deployment.md`](eval/fisco-deployment.md) and [`eval/demo_tx_hashes_fisco.md`](eval/demo_tx_hashes_fisco.md).
- **Local Anvil:** `scripts/deploy.py` and `scripts/evm_smoke.py` pass 7 of 7 checks.
- **Tests:** `pytest` 154 passed, 2 skipped (the classifier model tests). `forge test` 42 passed. The last fresh-clone check was at `fedd575`, with 135 passed.
- **Orchestrator:** the integration isn't finished. See `docs/orchestrator-integration.md`.

Per-item status is in the table in [`docs/03-agent-wallet.md`](../../docs/03-agent-wallet.md) section 8.

## Run (mock ledger)

Install the service's dependencies into a virtual environment first:

```bash
python -m venv .venv
.venv/bin/pip install -r services/agent-wallet/requirements.txt
```

On Windows, use `.venv\Scripts\pip` in place of `.venv/bin/pip`.

From the repo root:

```bash
export WALLET_OWNER_TOKEN=change-me WALLET_APPROVER_TOKEN=change-me-too WALLET_RISK_ORACLE_TOKEN=change-me-three WALLET_AGENT_TOKEN=change-me-four DEMO_MODE=1
python -m uvicorn app.main:app --app-dir services/agent-wallet --port 8003
```

The service starts with the demo mandate active and both lenders funded, so no seeding is needed. Then, in another
shell:

```bash
python services/agent-wallet/scripts/demo.py --url http://127.0.0.1:8003
```

On the mock, `demo.py` writes `eval/demo_tx_hashes.md`, and every hash in it is a mock hash (prefix `mock:`), not a
chain hash. `DEMO_MODE=1` is needed for the on-chain revert steps.

## Run on FISCO BCOS (4-node Air chain in Docker)

This needs Docker Desktop. The chain runs in an Ubuntu 22.04 container. Its data, keys and SDK config go in
`services/agent-wallet/fisco-chain/`, which git ignores.

1. **Chain folder and build script.** Create `fisco-chain/`, then download `build_chain.sh` from
   `tools/BcosAirBuilder/build_chain.sh` at the `v3.16.4` tag of `FISCO-BCOS/FISCO-BCOS` into it.
2. **Container.** Start it with the chain folder and the repo mounted, and the RPC, P2P and wallet ports mapped to
   localhost (paths in forward slashes on Windows):

   ```bash
   docker run -d --name fisco-air -p 127.0.0.1:20200-20203:20200-20203 -p 127.0.0.1:30300-30303:30300-30303 \
     -p 127.0.0.1:8003:8003 -v "<repo>/services/agent-wallet/fisco-chain:/work" -v "<repo>:/repo" \
     ubuntu:22.04 sleep infinity
   ```

3. **Tools and node binary, inside the container.** Install `curl ca-certificates openssl procps tar sed python3
   python3-venv`. Download `fisco-bcos-linux-x86_64.tar.gz` from the `v3.16.4` release, extract it to `/work/fisco-bin`,
   then run `bash build_chain.sh -l 127.0.0.1:4 -p 30300,20200 -e /work/fisco-bin/fisco-bcos` from `/work`. Start the
   nodes with `bash /work/nodes/127.0.0.1/start_all.sh`. Run the build script with `-e` because its own download uses a
   tag without the `v` prefix.
4. **Python SDK, inside the container.** Clone `FISCO-BCOS/python-sdk` to `/opt/python-sdk` and download the Linux
   native library `libbcos-c-sdk.so` (v3.4.0) into its `bcos3sdklib/`. Create a Python 3.10 virtual environment at
   `/opt/venv`, then install `setuptools==69.5.1`, the SDK's `requirements.txt` without its `pycryptodome` pin, and
   `services/agent-wallet/requirements.txt`. Python 3.10 is required: the SDK's vendored parser uses `getargspec`.
5. **Keys and SDK config.** Generate `deployer`, `agent`, `approver`, `risk_oracle` and `buyer` as secp256k1 PEM keys in
   `/work/accounts` (`openssl ecparam -name secp256k1 -genkey -noout -out <role>.pem`). Copy
   `fisco/sdk/*.template` to `/work/sdk/` without the `.template` suffix, and set `bcos3_lib_path` in `client_config.py`
   to `/opt/python-sdk/bcos3sdklib`.
6. **Deploy.** From `/repo/services/agent-wallet`, run
   `/opt/venv/bin/python scripts/deploy_fisco.py --sdk-dir /opt/python-sdk --config-dir /work/sdk --accounts-dir /work/accounts`.
   It writes the `fisco` block of `contracts/deployments.json` and every receipt to `eval/fisco-receipts/`.
7. **Wallet, inside the container:**

   ```bash
   cd /repo && CHAIN_MODE=fisco FISCO_SDK_DIR=/opt/python-sdk FISCO_CONFIG_DIR=/work/sdk \
     FISCO_RECEIPTS_DIR=/repo/services/agent-wallet/eval/fisco-receipts-demo \
     CHAIN_ACCOUNT_KEY_PATH=/work/accounts/agent.pem CHAIN_OWNER_KEY_PATH=/work/accounts/deployer.pem \
     CHAIN_APPROVER_KEY_PATH=/work/accounts/approver.pem CHAIN_RISK_ORACLE_KEY_PATH=/work/accounts/risk_oracle.pem \
     WALLET_OWNER_TOKEN=... WALLET_APPROVER_TOKEN=... WALLET_RISK_ORACLE_TOKEN=... WALLET_AGENT_TOKEN=... DEMO_MODE=1 \
     /opt/venv/bin/python -m uvicorn app.main:app --app-dir services/agent-wallet --host 0.0.0.0 --port 8003
   ```

   At startup the service checks that the chain's mandate hash is the demo mandate's, and refuses to start if not.
8. **Demo, in one command.** From the repo root, run `bash services/agent-wallet/scripts/fisco_demo.sh`. It starts the
   container, the four nodes and the wallet if they are not running, restarts the wallet so it uses the current code and
   tokens, runs `scripts/demo.py`, and checks every hash the demo wrote against the chain. Add `--fresh` to redeploy
   first. Set `PYTHON` if the host Python does not have `httpx`.
9. **Record.** The demo writes `eval/demo_tx_hashes_fisco.md` and each run gets its own run id. Receipts go to
   `eval/fisco-receipts-demo/`. The check's output is in `eval/fisco-verification-demo.txt`.

The daily cap is a rolling 24h total that every run adds to. The demo mandate allows THB 3,000,000. One full run draws
THB 1,504,300 (524,300 and 980,000), so a second run within 24 hours fails its large-draw step with `DailyCapExceeded`.
That refusal happens in the wallet, before any transaction, and the wallet reads the chain's total when it starts, so
restarting does not reset it. Use `--fresh` before a rehearsal or a recording. A fresh deployment also rewrites
`eval/fisco-deployment.md` from `eval/fisco-receipts/`, so that record matches the contracts the demo runs on.

## Test

```bash
pytest services/agent-wallet
ruff check services/agent-wallet
cd services/agent-wallet/contracts && FOUNDRY_SOLC=/path/to/solc-0.8.11 forge test --offline
```

The tests need `pytest`, `ruff` and `httpx` on top of the service requirements (`pip install pytest ruff httpx`).
The two classifier model tests run only when `INJECTION_MODEL_DIR` points at the pinned model.

The red-team eval: `python services/agent-wallet/eval/run_eval.py` (default cases, mock ledger). Pass
`--cases eval/heldout_v5_cases.jsonl` for another set, and `--skip-offchain` for the chain alone. Reports are in
`eval/report*.md`.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Service status and ledger mode |
| POST | `/wallet/register` | `X-Agent-Token` | TX-1: register a receivable, binding its seller (KYC-verified payees only) |
| POST | `/wallet/approve` | `X-Risk-Oracle-Token` | TX-2: record a credit approval; the decision must be sent and must match it |
| POST | `/wallet/execute` | `X-Agent-Token` | TX-4: guard, then draw; may return `pending_approval` or a held draft |
| POST | `/wallet/settle` | `X-Agent-Token` | TX-5: settle after the buyer pays |
| GET | `/wallet/holds` | approver token | Open held drafts (ids, amounts, codes; no invoice text) |
| POST | `/wallet/confirm/{tx_id}` | approver token | Release or reject a held draft or a pending payment |
| POST | `/wallet/pause` | approver or owner token | Stop all agent actions |
| POST | `/wallet/unpause` | owner token | Resume |
| POST | `/wallet/mandate/activate` | owner token | Activate a compiled mandate (out of bounds is HTTP 422) |
| GET | `/wallet/mandate` | none | Active mandate and its hash |
| GET | `/wallet/audit/{invoice_id}` | none | Audit entries for one invoice, plus `verified` |
| GET | `/wallet/audit/ref/{audit_ref}` | none | Audit entries for one action, plus `verified` |
| GET | `/wallet/tx/{tx_id}` | none | The result of one transaction |
| GET | `/wallet/audit/proof/{seq}` | none | Merkle inclusion proof for one audit entry against the anchored root |
| POST | `/wallet/audit/anchor` | owner or approver token | Anchor the audit log's Merkle root now |

A missing or wrong token gets HTTP 403. A malformed body gets 422 before the token check runs.
### Audit anchoring with Merkle proofs (`app/audit/merkle.py`)

After each settlement, and on demand, the wallet writes the **Merkle root** of the audit log on chain
(`AgentWallet.anchorAudit(root, entries)`, no contract change). It used to write the hash-chain head. The tree
follows RFC 9162 (Certificate Transparency v2), with 0x00 and 0x01 prefixes for leaves and nodes. An auditor
checks one entry with `GET /wallet/audit/proof/{seq}`: about log2(n) sibling hashes, and no other borrower's
entries. The check runs offline:

```bash
python services/agent-wallet/scripts/verify_audit_proof.py --url http://127.0.0.1:8003 --seq 25
```

It recomputes the entry's own hash from its contents, follows the path to the root, and prints the root and
the anchor's `chain_ref` to compare with the `AuditAnchored` event on chain. An edited entry, or one rehashed
to hide the edit, fails. The hash chain and `verified` are unchanged. `scripts/demo.py` section 8 prints one
verified proof.

Not built: `GET /wallet/registry/{invoice_fingerprint}` and the optional `POST /agent/run`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CHAIN_MODE` (`LEDGER_MODE` also accepted) | `mock` | `mock`, or `fisco` for the FISCO BCOS adapter on the deployed contracts. |
| `FISCO_SDK_DIR` | unset | Checkout of `FISCO-BCOS/python-sdk` (v3). Needed for `fisco`. |
| `FISCO_CONFIG_DIR` | unset | Folder with `client_config.py` and `bcos3_sdk_config.ini`. Needed for `fisco`. |
| `FISCO_RECEIPTS_DIR` | unset | Each FISCO transaction's receipt is saved here as JSON. |
| `CHAIN_DEPLOYMENTS_FILE` | `./services/agent-wallet/contracts/deployments.json` | Addresses; the `fisco` block is used in fisco mode. |
| `CHAIN_ACCOUNT_KEY_PATH` | unset | Agent key (PEM). Calls `AgentWallet.execute` and `anchorAudit`. |
| `CHAIN_OWNER_KEY_PATH` | unset | Owner key (PEM). Calls `setMandate`, `unpause`. |
| `CHAIN_APPROVER_KEY_PATH` | unset | Approver key (PEM). Calls `confirm` and `pause`. |
| `CHAIN_RISK_ORACLE_KEY_PATH` | unset | Risk-oracle key (PEM). Calls `Registry.approve`. |
| `WALLET_OWNER_TOKEN` | unset | Owner endpoints refuse every request until this is set. |
| `WALLET_APPROVER_TOKEN` | unset | Approver endpoints refuse every request until this is set. |
| `WALLET_RISK_ORACLE_TOKEN` | unset | `POST /wallet/approve` refuses every request until this is set. |
| `WALLET_AGENT_TOKEN` | unset | register, execute and settle refuse every request until this is set. |
| `DEMO_MODE` | `0` | `1` allows `skip_offchain_checks`, so the chain alone is tested. |
| `AGENT_CANARY` | unset | Canary string; seeing it in a request is a leak. |
| `INJECTION_MODEL_DIR` | unset | Folder with the pinned classifier model. Unset means rules only. |
| `INJECTION_CLASSIFIER_ACTION` | `log` | `log` audits classifier flags, `hold` holds them for an approver, `block` rejects them. |
| `WALLET_MAX_TX_AMOUNT` | `1500000.00` | Per-transaction cap (THB). |
| `WALLET_DAILY_CAP` | `3000000.00` | Rolling 24h cap (THB). |
| `WALLET_HUMAN_REVIEW_ABOVE` | `837500.00` | Draws at or above this need a human (inclusive). |
| `PLATFORM_FEE_RATE` | `0.003` | Platform fee as a share of face value. |

Money is THB with two decimals.

## Behaviour to know

- **Guard before the ledger.** L0–L4 checks run before any ledger call. Every failure is reported, and the reason is the
  first failing check in layer order. A blocked request never reaches the ledger.
- **Two layers of mandate checks.** The off-chain guard and the on-chain contracts (or the mock mirror) both enforce the
  mandate. Either one stops a payment. PD, mandate ID, currency and KYC are off-chain checks; the contracts enforce the
  money limits and the payee allowlist.
- **KYC.** Each payee in `config/payees.json` has a `kyc_verified` flag. An unverified seller is refused at registration
  (`KycNotVerified`), and only verified payees are allowlisted on chain. A `kyc_expiry` date, when set, makes the flag
  lapse after that day, and the seller is then refused the same way.
- **Time.** On FISCO, `block.timestamp` is in milliseconds. `PolicyGuard` takes a `timeScale` (1000 on FISCO) and works
  in seconds, so the mandate's expiry and the 24h window mean the same moment on both chains.
- **Holds.** In `hold` mode, a classifier-only flag stores the draft and returns `pending_approval`. The ledger is not
  called. Release re-runs every hard check. Holds expire after 24 hours.
- **Audit.** Each action writes a hash-chained entry per check and per outcome. Reads return `verified`, which
  is false if any entry has been changed or removed.
- **Decision freshness.** `valid_until` is read through a wallet-side request subclass (`DecisionFreshness`). The
  proper fix is a `contract:` PR that adds the field to shared `PolicyDecision`.
- **Approval binds the decision.** `/wallet/approve` needs the decision it names. The wallet recomputes its hash, and
  refuses unless it says `approve` and the request's `limit` and `fee_rate` equal the decision's. The draw re-checks
  the decision hash against the approved one.
- **Default draw key.** A draw sent without `idempotency_key` is keyed on its whole body, so a retry replays only the
  identical request.
- **Daily cap after a restart.** On FISCO, startup reads what `PolicyGuard` has counted in the last 24h and starts the
  off-chain cap from that total. The count runs for 24h from the restart, so it is never looser than the chain's
  sliding window, and the chain still enforces the exact one. If the read fails, the wallet does not start.

## Known gaps

- The decision is checked by hash, not signed. Shared `PolicyDecision` has no signature field, so whoever holds the
  risk-oracle token can approve a decision of their own.
- The risk-oracle key is in the wallet's environment in the MVP. The token gate is in; key separation is not.
- PD is checked off-chain only. With the guard bypassed, a draw above the PD ceiling executes (v5 cases S15 and S16).
- A draw is refused with `FeesExceedAmount` when the lender's fee and the platform fee together reach the draw amount.
  On the demo invoice, any draw under about THB 2,270 is refused.
- The classifier is English-only and does not detect jailbreaks. On the held-out v3 set, the rules alone catch 14 of 24
  attacks. On held-out v4, they catch 12 of 30.
- Holds and pending approvals are kept in memory. A restart loses them, and a confirm for a draw sent before the
  restart returns `NotPending`. The chain still holds the pending call.
- The FISCO adapter does not retry a transaction that fails at the RPC level; such a failure raises an exception.
- The 15-minute approval-age rule from CLAUDE.md §5.4 is not implemented.
- The optional agent loop (`POST /agent/run`, CLAUDE.md §7.3) is not built, so the eval skips its two cases.
- Console or python-sdk screenshots for the submission are not in the repo. The verification output and the receipts are.
