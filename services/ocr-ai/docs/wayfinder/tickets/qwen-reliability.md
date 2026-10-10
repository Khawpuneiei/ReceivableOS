---
name: Measure Qwen candidate reliability and alert errors
label: wayfinder:research
parent: ../map.md
status: resolved
assignee: codex-root
blocked_by: []
---

## Question

When does Qwen improve extraction coverage, and when does it introduce wrong monetary candidates or false injection alerts that increase review workload?

## Investigation

- Preserve the HTTP smoke counterexamples. Compare deterministic PDF/Paddle extraction, Qwen candidate outputs and the combined policy on identical inputs.
- Test subtotal versus VAT-inclusive grand total, multiple currencies, credit notes, benign payment instructions and genuine injection text. Change invoice references without changing monetary truth to detect prompt sensitivity.
- Repeat selected inputs at least three times. Pin model digest, prompt/schema version, input hashes and options; record invalid JSON, nulls, timeout and disagreement separately.
- Evaluate clean-document false alert rate, injection detection counts, candidate correctness, grounded acceptance, unresolved/review rate and latency by language/type/layout.
- Tune on the development partition only. Use the frozen independent holdout for the final recommendation. Decide whether Qwen should always run or serve a narrower candidate/review role based on measured tradeoffs.

## Evidence required to resolve

A reproducible comparison artifact and a decision about model role and prompt changes. JSON validity and model confidence must not substitute for verified document evidence. No critical-field replacement solely because the model sounds certain.

## Primary reference

[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) documents JSON-schema formatting and validation for vision responses. Local smoke results demonstrate why structural validity still needs a separate factual grounding check.

## Resolution

See the [six-workstream reliability review](../../RELIABILITY_REVIEW.md) and [baseline evidence](../../RELIABILITY_BASELINE.json). The experiment identifies a bounded next step without granting model outputs field-writing authority.
