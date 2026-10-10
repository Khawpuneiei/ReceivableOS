# OCR and fraud research findings

Date: 10 October 2026. Scope: ReceivableOS OCR, invoice-to-PO comparison, and invoice evidence graph. The measurements below are local synthetic-corpus results, not production accuracy estimates.

## Current language check

The current [reliability evaluation](RELIABILITY_EVALUATION.json) runs all 80 generated documents through PDF text extraction or the explicitly selected PaddleOCR language profile for scans. The latest complete run reports:

| Language | Documents | Correct header fields | All seven fields matched | Correct line counts | Wrong non-null fields |
|---|---:|---:|---:|---:|---:|
| English | 48 | 336 / 336 | 48 / 48 | 48 / 48 | 0 |
| Simplified Chinese | 16 | 112 / 112 | 16 / 16 | 16 / 16 | 0 |
| Thai | 16 | 99 / 112 | 8 / 16 | 14 / 16 | 0 |

Chinese PDF text-layer inputs contribute 56 / 56 correct header fields; Chinese scans evaluated with the explicit `PP-OCRv5_mobile_rec` profile contribute 56 / 56. The extractor retains Simplified Chinese labels and values, but marks all Chinese documents `EXPERIMENTAL_CHINESE_REQUIRES_REVIEW`. Therefore these are successful synthetic extraction tests, not support for unattended Chinese invoice processing. The scan evaluation selects a language profile from trusted corpus metadata; the live service does not automatically route a scan to Chinese OCR.

An OCR-enabled multipart `/ocr/extract` smoke on `invoice-zh-stacked-1.png` also returned HTTP 200 with the expected invoice number, CNY amount, Paddle engine identity, and mandatory experimental review flag.

Thai's 13 missing header matches are abstentions, not wrong values. Most missing values are invoice or PO numbers in the scanned layouts; two commercial-layout scans also miss other fields. They remain review cases. English and Chinese had no wrong non-null field on this generated corpus. These high match rates are expected to overstate real performance because the generator and labels share the same templates and vocabulary; the layout-family holdout is not an external vendor holdout.

The previous Qwen experiment is recorded in [RELIABILITY_BASELINE.json](RELIABILITY_BASELINE.json). Its eight Chinese scan files are the same eight PNGs in the Paddle evaluation: each model matched all 56 annotated header fields across those unique inputs. Qwen made 12 calls because stacked cases were repeated; all 12 calls raised an injection alert on benign payment text. The repeats are not additional independent documents. There is no Chinese extraction-accuracy advantage for Qwen in this synthetic comparison, and its false alerts add review noise. Qwen remains a candidate source of suggestions; it does not supply accepted values or remove review requirements.

## Invoice revisions and altered documents

The live flow now adds `REVISION_OR_CREDIT_NOTE_REQUIRES_REVIEW` when it sees explicit English, Simplified Chinese, or Thai revision/correction/replacement, credit/debit-note, or cancellation markers. The rule is deliberately a review signal: it does not infer that a later document legally replaces an earlier invoice.

The observation graph recognizes `near_duplicate` when the same scoped parties, invoice reference, currency, and issue date reappear with a different amount. It now also emits `bank_account_changed` when the same scoped supplier's most recent prior observation has a different bank token. API regression coverage verifies both review signals, that the graph links the two invoice observations, and that neither account number appears in the response. This additive graph relation is identified by `ocr-graph-v2` / `graph-rules-v2`. Inconsistent arithmetic also raises `math_inconsistent`.

These checks cannot prove authenticity. A single internally consistent file with no prior observation may evade revision-history, payee-change, and arithmetic checks; coherently changing all printed totals is not visible from the isolated values alone. The service has no invoice-version lineage, issuer-authoritative replacement relationship, cryptographic issuer signature validation, or pixel-level tamper localization. A marker or graph match is a candidate for investigation, not evidence of fraud by itself.

The full service suite passes 145 tests, including the new Chinese, revision, changed-payee, evidence-privacy, and graph-version regressions. Five PyMuPDF/SWIG deprecation warnings remain.

## Research that applies to this scope

| Source | What it contributes | How to use it here |
|---|---|---|
| [DocILE benchmark paper](https://arxiv.org/abs/2302.05658) and [official dataset repository](https://github.com/rossumai/docile) | Business-document key-information localization and line-item recognition, with field locations and line membership; useful evaluation tasks beyond scalar text accuracy. | Prioritize as an independent English business-document evaluation candidate. Check dataset terms, access and language coverage before adding it; no data was downloaded for this change. |
| [XFUND, ACL Findings 2022](https://aclanthology.org/2022.findings-acl.253/) | Human-annotated forms in seven languages, including Chinese, with key/value structure. | Use Chinese XFUND examples to stress-test multilingual labels and layout relationships if the license/terms fit. It is a form benchmark, not an invoice benchmark, so keep it separate from invoice accuracy claims. |
| [AIForge-Doc, arXiv 2026 preprint](https://arxiv.org/abs/2602.20569) | Paired, localized AI-inpainted changes to financial/form documents. The paper reports substantial out-of-distribution degradation for its evaluated forensic detectors and a near-chance zero-shot VLM judge. | Treat visual-forensics models as one review signal, not an authenticity oracle. Evaluate on paired invoice edits and report localization and false-alert rates before considering integration. Verify dataset release and license first. |
| [DocTamper, CVPR 2023 paper](https://openaccess.thecvf.com/content/CVPR2023/papers/Qu_Towards_Robust_Tampered_Text_Detection_in_Document_Image_New_Dataset_CVPR_2023_paper.pdf) | Tampered-text detection and a document-image forgery benchmark. | A possible traditional image-edit baseline after checking source-domain and license fit; its image-domain results do not establish invoice fraud detection quality. |

## Recommended next work, in order

1. **Replace synthetic-only confidence with independent evaluation.** Obtain permissioned English business invoices and Chinese invoice examples with reviewed field values, bounding boxes, line-item grouping, and known revision/alteration labels. Split by source organization and template family, not random pages. Keep the existing synthetic pack for regression and adversarial cases.
2. **Measure the review boundary.** For each language and input type, report field-level precision/recall, exact normalized matches, line-item tuple F1, evidence-location validity, wrong-present rate, abstention rate, and the percentage of documents that would reach review. Separate digital PDFs from scans and hold out complete vendors/layouts.
3. **Close scan-routing gaps.** Add a controlled multilingual routing experiment for English, Simplified Chinese, and Thai; evaluate native language profiles on the same paired scans, including low-resolution, rotated, multi-page, mixed-language, and Traditional Chinese inputs. Do not infer language from document instructions or a filename.
4. **Model revision relationships explicitly.** Add reviewed examples for corrected/replacement invoices, credit/debit notes, cancellations, and changed payee details. Preserve the original and candidate document hashes, observed version references, dates, amount deltas, and evidence. Only an authorized registry or reviewer should decide which version is authoritative.
5. **Evaluate edit signals with paired evidence.** Create source-controlled clean/altered pairs for amount, invoice number, dates, and bank details; retain pixel masks and PDF revision metadata where available. Combine arithmetic and history signals with signature/provenance and image-forensics evidence, but test each signal's false-alert rate on benign revisions and scanned/recompressed documents.
6. **Calibrate the fraud graph on reviewed outcomes.** The current graph and score weights are rules, not learned probabilities. Collect adjudicated duplicate, shared-account, benign group-payment, correction, and false-alert outcomes. Report precision/recall and calibration by signal and cohort before changing score semantics. Bank ownership remains a separate verified-data responsibility.

The immediate safe result is a multilingual, evidence-grounded review assistant. It is not yet an autonomous invoice approver or an authenticity verifier.
