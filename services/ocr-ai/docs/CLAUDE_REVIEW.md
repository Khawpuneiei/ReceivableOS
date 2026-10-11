# OCR service guide review

**Reviewed:** 2026-10-10; status updated 2026-10-11 after main merge 7c7056c
**Branch checked:** `ocr/evidence-fraud-graph`
**Scope:** OCR service guide, repository ownership rules, product scope, current OCR implementation and the automated demo loop.

## Assessment

`services/ocr-ai/CLAUDE.md` is a useful, detailed operating guide and does not depend on Claude Code or a Claude account. It describes the current local OCR design more accurately than a generic assumption that all LLM calls use a hosted provider. The root `CLAUDE.md` remains the authority for ownership, shared APIs, team workflow and definition of done; `docs/00-scope.md` remains the product/interface source of truth. The service guide correctly tells contributors to resolve conflicts rather than editing another team's code or the shared contract from an OCR-only change.

The latest main merge replaces the prior fixed-approve Policy stub with a tested Policy implementation. The integrated demo now verifies injection → review and fraud score 0.70 → reject with zero guard violations. The remaining service-boundary gap is unchanged: the shared request carries only the `ExtractedInvoice` projection, not the OCR pair-comparison, supporting-case, or full graph evidence.

## Rule-by-rule implementation check

| Guide requirement | Current implementation / test evidence | Assessment |
| --- | --- | --- |
| Stay on `ocr/evidence-fraud-graph`; preserve other work | Current branch checked before edits; work is limited to `services/ocr-ai/`, OCR-owned data and `docs/05-ocr-ai.md` | Followed |
| OCR owns Invoice/PO reading, local fraud signals and review handoff | `/ocr/extract`, `/ocr/verify`, `app/pipeline.py`, local fraud graph and handoff models | Implemented within OCR ownership |
| Values must be grounded; unknown/ambiguous remains unresolved | `DocumentExtraction`, `FieldValue`, source evidence references, comparison checks and model validators | Implemented; current fixtures are synthetic |
| The OCR result is not a financing decision | Service response is evidence only; the new runner separately records Policy's decision | Correct boundary; consumer enforcement remains missing |
| Injection warning should lead to review | OCR identifies the visible prompt and sets review; the merged Policy endpoint returns `review` | Verified in the current integration loop |
| Fraud score at/above 0.30 should be rejected by Policy; confidence below 0.80 should be reviewed | An OCR amount mismatch produces score `0.70`; current Policy returns `reject`. Current Policy suite passes 251 tests with 3 skipped | Fraud guard verified in integration; confidence path is covered by Policy tests |
| Pair mismatches cannot become matches; missing evidence stays unknown | `/ocr/verify` uses distinct Invoice and PO uploads, typed checks and validators; generated clean/mismatch pairs run through HTTP | Implemented for Invoice and PO |
| Exact/semantic duplicates, scoped shared-bank tokens and suspicious clusters | Synthetic `eval.py` risk sequences cover duplicates, near duplicate, benign account sharing and independent suspicious clusters in English and Thai | 10/10 planted sequences surfaced expected codes; not a real-world precision/recall result |
| Keep bank observations private and graph outputs scoped | Runner emits selected fields, fraud codes and graph counts/relations only; generated result is scanned for raw sample account formats | Report privacy check passes; full production log/telemetry review remains separate |
| English-primary; Thai and Simplified Chinese explicit/experimental; no language router | Current README, model configuration and reliability plan specify explicit language profiles | Correctly scoped; do not claim general multilingual coverage |
| PDF text first; staged local Paddle for unreadable scans; optional local Qwen is candidate-only | Current pipeline and service docs retain PDF text/layout as first path, Paddle scan fallback and Qwen candidate constraints; both are disabled in this deterministic integration run | Consistent; the demo loop does not benchmark models |
| Keep limits, keys and state isolated; don't add a reset HTTP route | New loop starts services on free loopback ports, uses temporary SQLite and ephemeral keys, runs with Paddle/Qwen disabled, then terminates processes and removes generated fixtures | Followed for this test path |
| Keep shared contract, orchestrator, Policy, Wallet and other data owner-controlled | No edits were made outside `services/ocr-ai/`; the loop calls the owner services locally but does not change their code | Followed |
| `run_demo.py` must work and mock mode must not require external LLM access | The loop invokes the unchanged `services/orchestrator/run_demo.py` with an explicit generated PDF, `CHAIN_MODE=mock` and model calls disabled | Verified; the explicit path avoids the stale default fixture path |

## Product-scope cross-check

The project finance-domain document names Invoice, PO and delivery/receipt evidence in the receivable lifecycle. UBL and Peppol document models also distinguish order, invoice, despatch, receipt, credit/debit note, and supporting references. However, the present OCR API only accepts an Invoice for extraction and an Invoice plus PO for pair verification. Delivery note, goods-received note, buyer acceptance, credit/debit note, contracts, settlement, transport, assignment, KYB, authority and financial statements are future typed evidence; they must not be represented as already supported because a related field appears in a demo profile.

The detailed inventory and support matrix are in [DOCUMENT_CATALOG.md](DOCUMENT_CATALOG.md). Global and Thai document formats vary, and the catalog treats standards and regulator material as design references rather than universal document mandates.

## Automated result

The reproducible synthetic HTTP loop is in [DEMO_LOOP_RESULTS.json](DEMO_LOOP_RESULTS.json). It creates temporary polished invoice and PO examples, runs the existing end-to-end demo, checks selected extracted values and evidence references, retries the same invoice, calls `/ocr/verify` for a clean and inflated-amount pair, routes injection through the orchestrator, submits a high-score pair projection to the actual Policy endpoint, and runs the existing ten synthetic fraud graph sequences.

The latest full release run recorded:

- OCR tests: **184 passed** locally and **184 passed** in a fresh clone.
- Policy tests: **251 passed, 3 skipped**.
- Strict integrated demo: **6/6 OCR checks passed**, injection returned `review`, high-score mismatch returned `reject`, and Policy guard violations were **0**.
- Ordered OCR evidence gate: clean, injected, inflated, and duplicate expectations all passed. Separate synthetic risk evaluation surfaced all 12 expected English/Thai sequences.
- Clean Invoice/PO pair: `matched`; amount-mismatch pair: `mismatch`, `po_amount_mismatch` and `math_inconsistent`, score `0.70`, review required at OCR.
- Wallet returned `pending_approval`; this remains a stub state, not an executed payment or chain transaction.
- Raw sample bank account values and graph node IDs are not written to the report.

## Recommended next changes by owner

1. **OCR owner:** continue to add typed extraction/comparison and synthetic regression fixtures for one evidence type at a time, beginning with delivery/receipt or buyer acceptance. Preserve `unknown` when evidence is absent and do not claim that OCR establishes authenticity or authority.
2. **PM / shared-contract owner:** review a versioned evidence-bundle contract that carries Invoice/PO comparison, review reasons, fraud codes, score semantics, source hashes and the unsigned/authentication status. Do not extend `shared.schemas` from the OCR patch alone.
3. **Policy owner:** preserve the now-passing injection, fraud-score and confidence guard tests; agree the OCR reason-code adapter and support the separately reviewed evidence contract when approved.
4. **Orchestrator owner:** decide how a case submits Invoice, PO and supporting evidence together and ensure the pair/handoff reaches Policy. The present `/flow/run` accepts only one file and uses an in-memory duplicate registry.
5. **Wallet/security owners:** independently authenticate decision/evidence bindings, validate mandate and payee authority, and enforce the final execution guard. OCR output alone must never authorize execution.
6. **Evaluation owners:** obtain a separate, permissioned, human-labeled holdout across vendor families and languages before claiming real-world extraction or fraud performance; keep the current synthetic sets as development/regression data.

These owner assignments are recommendations from the reviewed rules and observed code. The latest increment also implements hosted candidates/cache, QR inspection, protected result retrieval and limited supporting-template case extraction; it intentionally leaves cross-service contract work for the owners named above.

## Checklist-driven additions

The guide documents the hosted candidate adapter, token-protected RAM result retrieval, observation-free cache prewarm and English supporting templates. Offline operation needs no cloud account. The shared schema remains unchanged; current Policy guard checks pass, while full pair/graph evidence adoption remains open. Evidence: [checklist](CHECKLIST_AND_DEMO.md), [fresh release check](RELEASE_CHECK.json), [case loop](CASE_LOOP_RESULTS.json), [model check](CHECKLIST_MODEL_CHECK.json). General document authenticity and live hosted accuracy remain unverified.

## Owner handoff and independent-source follow-up (11 October 2026)

The OCR-owned follow-up is recorded in [POLICY_INTEGRATION_HANDOFF.md](POLICY_INTEGRATION_HANDOFF.md): it documents passing guards, the `duplicate_invoice_hash`/`duplicate_fingerprint`/`po_amount_mismatch` versus Policy reason-code distinction, and an additive versioned bundle proposal. This OCR work does not edit Policy, Orchestrator, or shared schemas. PM contract review and orchestrator evidence routing remain open owner tasks.

[DATASET_ACCESS_AND_HOLDOUT.md](DATASET_ACCESS_AND_HOLDOUT.md) records the source review and frozen evaluation protocol. DocILE is a relevant English business-document candidate but requires a dataset token; XFUND is a Chinese form benchmark under CC BY-NC-SA 4.0 rather than an invoice set; SROIE is scanned receipts and its linked data rights need separate confirmation. No external corpus was downloaded or treated as a fraud-label set. The bank token remains a privacy-scoped correlation signal; ownership verification requires an authorized external provider and consent.
