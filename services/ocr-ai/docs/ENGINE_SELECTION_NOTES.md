# Earlier Qwen selection experiments

The initial local experiments selected `qwen3-vl:4b-instruct` rather than the Thinking tag: the Thinking variant exhausted the bounded 512-token generation budget without returning usable schema data. An optional-field schema also permitted null-only output. Every nullable field is now required, with extra properties forbidden and post-response validation.

An earlier Thai example selected the printed subtotal instead of the VAT-inclusive grand total. The grand-total-payable prompt improved the original four-scan result, but subsequent HTTP cases still showed monetary disagreements and false injection alerts. These observations motivated the English-primary reliability evaluation; prompt refinement does not replace source grounding.

Superseded per-attempt JSON artifacts were consolidated into this note during cleanup. Keep [the original selected-engine benchmark](ENGINE_BENCHMARK.json), [historical HTTP smoke](HTTP_SMOKE.json), and the new reliability results as the useful comparison evidence. No accuracy claim is based on the removed experiments.
