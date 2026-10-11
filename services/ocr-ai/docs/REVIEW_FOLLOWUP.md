# PM review follow-up — 11 October 2026

Review: [PR #16, latest PM comment](https://github.com/Khawpuneiei/ReceivableOS/pull/16#issuecomment-6105621941).
Branch: `ocr/evidence-fraud-graph`. Shared schemas and other-service implementations are unchanged.

| Review request | Change / verification |
|---|---|
| Keep orchestrator's default text sample | Original `data/invoices/demo_invoice.txt` restored unchanged. Explicit development-only, exact-byte allowlist; source-offset extraction and raw hash. Modified text →415. Missing jurisdiction/unit →review. Actual unchanged `run_demo.py` tested without arguments against a fresh mock registry |
| No-key development setup | `OCR_DEVELOPMENT_MODE=1` supplies separate public demo HMAC keys, warning once per setting; default production mode stays fail-closed. README documents random-key setup, both keys and explicit development run |
| PR size and generated reports | 32 generated JSON reports removed from version control. 167 rendered/source corpus files and 34 experimental documents/files split out of core. Core retains service/tests, four PDFs, legacy text and a licensed Thai test font. Tests generate their corpus in temporary directories |
| Reference normalization | Strip numeric-run leading zeros before joining separators. Unit test plus multipart/HMAC/duplicate-rule regression: `INV-2026-0042` equals `INV-2026-42` and differs from `INV-202-60042` |
| Restore guide §8.4 | Registry-v1 raw hash, canonical fields, HMAC, numeric-run order, dev key and migration caveat documented under the exact cited section |
| Re-saved duplicate sample | 04 has changed PDF metadata/bytes and unchanged printed fields; different doc_hash, same fingerprint, `duplicate_fingerprint`, score 0.80. Byte duplicate remains separately tested |
| Local machine paths | Committed documentation uses repository-relative paths; release runner replaces local root in command/log summaries. Generated results stay ignored |
| Explicit hosted opt-in | `OCR_HOSTED_VISION_ENABLED=1` required in addition to key/provider/model. Key alone produces no upload or hosted model check; transport tests use fake keys and mock responses |
| Cache lock blocks unrelated documents | Per-key single-flight for both hosted and Qwen readers. Same key calls model once; distinct keys progress during blocked network I/O. Transient lock bookkeeping cleaned on success/failure |
| Reset run steps | README provides operator-only reset with `OCR_DEVELOPMENT_MODE=1` and `OCR_ALLOW_RESET=1`, exact state-path warning and no reset HTTP route |

The original full work is preserved locally at `ocr/archive-before-review-20261011` (f13ec0b). Companion `ocr/corpus-evidence` carries source data, attribution and experiment documentation. No generated evaluation JSON is committed to either PR; scripts regenerate it. The core is still a substantial implementation, but the largest report/render noise has been removed rather than hiding it in history rewriting.

## Cache measurement

`python scripts/benchmark_cache.py` drives the real hosted adapter and strict response parser through `httpx.MockTransport`, with two distinct image keys and two threads. Each transport call sleeps 0.25 seconds. Baseline: **0.5177 seconds**, two calls; fixed: **0.2580 seconds**, two calls. This is about half the total wall time for this controlled contention case, not a live OCR/model latency claim. An event-based regression verifies distinct-key progress without a fragile timing threshold. Identical-key tests verify that billable calls are deduplicated. Model response failures are not cached.

The review defects were reproduced first: five new regression failures showed normalization mismatch, development 503, legacy 415, missing hosted opt-in and distinct-key contention. Existing production fail-closed cases stayed green. No cloud model or source-data upload was performed for these checks.

## Validation

See README for exact reproduction commands. The strict local integration loop passes **7/7** checks with **zero Policy control violations**, including PM default text →review, injected PDF →review, amount mismatch →reject, clean PO comparison and registry duplicate blocking. The ordered four-PDF gate passes **4/4**, with scores 0.00, 0.00, 0.40 and 0.80.

The clean-clone check exposed a coupling between core metric tests and the optional experiment evaluator. The core now contains a pure `scripts/evaluation_metrics.py` helper; the full reliability evaluator is companion-only. The targeted canonical-three-decimal regression passes in both checkouts. A full clean-clone release check is required after this split. Its generated `docs/RELEASE_CHECK.json` records fresh install, regenerated data, pytest, Ruff, pip check and actual HTTP extraction/retrieval on port 8001. Results and metrics are summarized in `docs/05-ocr-ai.md` after completion; these synthetic checks do not establish production fraud precision or independent-vendor extraction accuracy.

## Latest main integration

Main `7d46da5` (Wallet PR #17) was merged without conflict. Policy tests: **251 passed / 3 skipped**. Wallet tests: **122 passed / 2 skipped**. Companion-only grounding/publisher coverage: **13 passed**, with Ruff clean. The actual clean run reaches Policy approve but Wallet returns **blocked / SchemaInvalid**; the PM orchestrator still sends the old execute payload without complete fingerprint/intent fields or Registry/credit-approval lifecycle. This is a PM integration dependency, not a reason to bypass the Wallet guard. The OCR release scope does not claim successful funding.

## Limits retained

English remains primary, Thai secondary and Chinese experimental/review-only. This change improves correctness and concurrent candidate throughput; it does not improve raw scan recognition accuracy or resolve global-layout gaps. The published synthetic invoice pack is development data and its prior 77.59% header accuracy is below target. Independent licensed holdouts, confirmed fraud labels, live hosted inference, issuer/bank authentication and real settlement remain unverified. PO/case/graph consumer adoption still requires a PM-reviewed contract; HMAC normalization changes require a reviewed history migration for live state.
