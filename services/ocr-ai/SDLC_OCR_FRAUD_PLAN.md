# OCR + Fraud Detection — SDLC Execution Plan

**Repo:** `Khawpuneiei/ReceivableOS` (private)  
**Feature branch created:** `ocr/evidence-fraud-graph` (forked from `main` on 2026-10-10)  
**Owner paths:** `services/ocr-ai/**`, OCR-owned `data/invoices/**`, `docs/05-ocr-ai.md`  
**Team source of truth:** root `CLAUDE.md`, `docs/00-scope.md` and `shared/schemas.py`.

## Verified repository baseline
- `services/ocr-ai/app/main.py` is a **fixed-response stub**: reads file for SHA-256 but returns the same Siam Fresh Pack invoice fields, `confidence=0.5`, `fraud_flags=["stub"]` regardless of input. Real extraction, injection and graph models **are not implemented**.
- OCR service requirements presently contain only FastAPI, uvicorn, Pydantic and python-multipart. Only OCR health test exists.
- Contract: `POST /ocr/extract` multipart `file` -> `ExtractedInvoice`, including `doc_hash` and `invoice_fingerprint`. The PM owns `shared/schemas.py`; changing its shape requires a separate reviewed contract PR.
- Orchestrator currently performs an **in-memory** duplicate check keyed on `invoice_fingerprint` before calling policy, not an on-chain registry. Treat this as a stub, not proven double-financing protection.
- Policy's current `POST /policy/decide` is also stub and does not yet enforce its stated thresholds; end-to-end demos must not treat successful financing as evidence that the fraud controls work.
- Repo contains root and OCR-local `CLAUDE.md` specifications, `docs/05-ocr-ai.md` and synthetic demo invoice text; this plan supplements them without replacing design decisions.
- Team internal freeze: **2026-10-12 12:00 Asia/Bangkok** (per `docs/00-scope.md`), so prioritize demonstrable, tested slices.

## Research-derived framing versus actual implementation
**From attached specialization roadmap:** Evidence pipeline = document OCR/parser -> structured extraction -> schema validation -> cross-document matching -> evidence graph. Fraud layers = document validation + rules + entity matching + graph + optional anomaly detection. File hash establishes byte integrity only, **not invoice truth**.

**Design recommendation, NOT presently built:** Use PDF text-layer parsing and deterministic template extraction for offline demo; optional vision reader if network configured; load synthetic PO master reference data; NetworkX graph of companies, bank accounts, addresses and directors; seeded fraud cases; explainable rule scoring. Real vendor/bank/PO integration requires future approval and stronger identity validation.

## Scope and contract decisions

| Item | MVP handling | Contract owner |
|---|---|---|
| `POST /ocr/extract` | Keep existing multipart invoice upload + shared output. | OCR implementation; PM owns shared model |
| PO matching | Read synthetic `data/invoices/master/pos.json`; compare invoice `po_no`, tax IDs, amounts, currency, remaining PO value, duplicate allocation. | OCR-local enhancement |
| User uploads PO separately | **Not supported in current shared route**. First submit proposed optional OCR-owned endpoint or multipart field to PM, rather than silently altering shared contract/orchestrator. | PM approval |
| Extra flags/path evidence | Optional `OcrExtractResponse(ExtractedInvoice)` response subtype; keep existing fields unchanged. | OCR |
| Registry duplicate state | Compute fingerprint in OCR; chain registry/enforcement handled by wallet/PM. | Wallet + PM |
| Credit, pricing, lender selection | Consume OCR outputs only. No OCR-side loan approval. | Policy/PM |
| Real KYB/bank account verification | Future only; graph claims are synthetic risk indicators. | PM/Compliance |

## MVP risk rules and explainable graph

1. **Exact duplicate:** same `doc_hash`, repeated upload -> `duplicate_invoice_hash`. Exact file match is not enough for re-rendered copies.
2. **Semantic duplicate:** normalize supplier + buyer + invoice number + amount + currency + date, compute keyed `invoice_fingerprint`; same canonical identity across different bytes -> `duplicate_fingerprint`. Resist accidental reuse across test setup via controlled reset.
3. **PO consistency:** independently verify the referenced PO belongs to the right supplier/buyer, matches currency and permitted quantity/remaining amount; status distinguishes missing PO, partial shipment, amount mismatch and party mismatch. Do **not** compare only invoice total to PO total when VAT/partial invoicing exists. Use same basis and explicit tolerance.
4. **Bank account mismatch/shared:** compare normalized, privacy-minimized identifiers against synthetic master records; a shared identifier is a *review signal*, not proof of collusion. Never reveal raw account numbers in publicly rendered graph or logs.
5. **Graph suspicious cluster:** entities `company:<taxid>`, `bank:<hashedref>`, `director:<token>`, `address:<token>`, and historical `invoiced` edges with timestamps. Analyze short cycles (length <=3) constrained by 90 days, 10% amount tolerance, and sufficiently distinct business identities. Preserve paths/evidence so reviewer can reproduce why flagged. Require minimum evidence, limit graph size, no open-ended `simple_cycles` on uncontrolled graphs.
6. **Injection:** invoice text in plain/hidden PDF spans, metadata or QR must never become AI instructions. Return `injection_flags`; do not mutate monetary data from injected text.
7. **Fraud score:** named, bounded, versioned deterministic rule weights; avoid building a model simply to claim AI/ML. Score is **heuristic risk**, not calibrated fraud probability.

## SDLC mini-backlog (one PR per slice)

| Slice / branch example | Deliverable | Gate |
|---|---|---|
| PR1 `ocr/contract-fixtures` | Optional detail schemas, config, clean/attack fixtures | Response validates as `ExtractedInvoice`, tests pass |
| PR2 `ocr/pdf-extraction` | Safe file ingest, PDF text and deterministic parser, Decimal validation, stable fingerprints | Extract five independent synthetic invoices offline; no fixed stub data |
| PR3 `ocr/po-cross-check` | PO master fixtures, validation and matching with parties, currency and partials | clean match, false PO, inflated invoice and partial delivery tests |
| PR4 `ocr/duplicate-rules` | SQLite history, exact/semantic duplicates, math and master-data rules | idempotent replays; clean false-positive checks |
| PR5 `ocr/fraud-graph` | NetworkX graph, shared bank/director, short cycle, evidence paths | controlled planted cases detected; innocent shared signals not automatically rejected |
| PR6 `ocr/injection-tests` | Hidden-text metadata, PDF input sanitization and negative cases | poisoned text flagged, clean extraction unchanged |
| PR7 `ocr/evaluation` | seeded labeled data, deterministic metrics script, updated OCR README | reproducible results, no invented benchmark scores |

**Timebox:** for the Oct 12 freeze, finish PR1–4 plus one graph case and injection tests before spending time on optional vision LLM or IsolationForest. If a different branch is used for every PR, base sequential branches on the latest reviewed OCR branch, or merge PR1 then branch PR2 from the latest main; avoid parallel branch divergence that produces duplicate features.

## Evaluation protocol
- Set `seed=42` and label all synthetic files. Report file number, fraud cases and benign hard negatives.
- OCR: field-normalized exact-match accuracy (amount, invoice_no, dates, parties), invoice-level full exact-match, latency p50/p95; PDFs vs images separately.
- PO: precision/recall on intentionally mismatched references, party/amount/currency mismatch categories; include partial invoicing and VAT cases.
- Fraud: per-case detection rate, precision, recall, false-positive rate, PR-AUC only if a varying score is meaningfully evaluated; compare **rules-only versus rules+graph** on the same split and order.
- Leakage control: paired clean/injection twins must remain grouped for evaluation, not separated across train/test if learning models.
- Fair claim: results apply only to the team's labeled synthetic fixtures; do not cite numbers as performance on real trade-finance data.

## Security / data hygiene
Enforce upload file-size/page limits, MIME+magic-byte validation, timeouts and image pixel ceilings; no path traversal, no writing arbitrary filenames, no shell execution, no untrusted document prompts treated as system instructions. Use environment-based HMAC keys; never commit `.env`, real invoices or banking information. Hash or tokenize graph account identifiers; maintain a minimal audit trace with file hash, rule id, evidence and model/rule version. An unavailable PO registry or incomplete graph should lead to **unknown/review**, not `verified`.

## Local commands

```bash
git clone https://github.com/Khawpuneiei/ReceivableOS.git
cd ReceivableOS
git fetch origin
git switch ocr/evidence-fraud-graph
git status --short --branch
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest services/ocr-ai
ruff check services/ocr-ai
python -m uvicorn app.main:app --app-dir services/ocr-ai --port 8001 --reload
```

For existing local clones, use `git status` before switching; do not `reset --hard`, `clean -fd` or delete other branches. Add new package dependencies only to `services/ocr-ai/requirements.txt` and explain installation/licensing. Run all service tests when integration PR is ready.

## Pull request description (paste)
```markdown
## Scope
OCR AI only. No breaking API / shared schema changes.

## Changes
- ...

## Test evidence
- pytest services/ocr-ai:
- ruff check services/ocr-ai:
- synthetic cases tested:
- baseline-vs-change metrics:

## Security/privacy
- injection boundary:
- uploads limits:
- HMAC key handling:
- data origin: synthetic only

## Impact
- ExtractedInvoice contract preserved? yes/no
- Orchestrator mock flow checked? yes/no
- Known limitations:
```

## Research pointers to read before expanding
- Repository's `docs/05-ocr-ai.md` and `services/ocr-ai/CLAUDE.md` (first authority; already contain rules/scoring proposals and seeded sample cases).
- Attached `receivableos_specialization_roadmap.md`, especially sections Track D (Fraud), Track E (Evidence), Track F (Data), Track M (Security), Track P (Evaluation).
- PyMuPDF official documentation: https://pymupdf.readthedocs.io/en/latest/
- NetworkX reference: https://networkx.org/documentation/stable/
- Pydantic models: https://docs.pydantic.dev/latest/
- OWASP LLM Prompt Injection Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
- FATF trade-based money laundering risk indicators: https://www.fatf-gafi.org/en/publications/Methodsandtrends/Trade-based-money-laundering-risk-indicators.html

> **Important caveat:** filenames and graph algorithms above are recommendations; the only confirmed committed OCR implementation at assessment time was the fixed stub. Do not mistake roadmap descriptions for code already present.
