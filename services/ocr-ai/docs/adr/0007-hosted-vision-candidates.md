---
status: implemented-locally
date: 2026-10-10
---

# Add keyed hosted vision while preserving grounded field authority

The user explicitly chose a hosted LLM adapter in addition to the earlier local Paddle/Qwen design. Offline extraction must still run without a cloud API key. Hosted model output shares the strict nullable candidate schema with Qwen; proposals cannot fill unresolved source fields or replace printed evidence. Disagreement, refusal, invalid output or transport failure requires review.

Use a thin `app/llm_client.py` Anthropic Messages adapter with explicit provider/model/key, an HTTPS endpoint fixed in code, no tools, bounded response and no automatic retries. Rendered pages are sent outside the machine when configured, so deployment data handling belongs to the owner; no source images, raw text, API key or prompts are logged/persisted by this service.

Cache successful typed candidates in bounded process-local RAM keyed by provider/model/account identity/prompt/schema/images. Account identity is hashed without retaining its key. RAM protects against persistent document copies but loses demo warming on restart and does not provide multi-worker cache sharing. A protected prewarm endpoint does not observe/register invoices, preventing cache preparation from contaminating duplicate tests. This supplements the local-engine decision; live hosted inference remains unverified until configured and measured.
