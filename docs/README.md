# ReceivableOS docs

One doc per topic. Each is owned by its author and added by its own PR; links below will work as they land.

| Doc | Topic | Owner |
|---|---|---|
| [00-scope.md](00-scope.md) | MVP scope, ownership, interface spec (section 4), demo story | PM |
| [01-architecture.md](01-architecture.md) | System architecture, data flow, trust model, contracts | PM (research) |
| [02-finance-domain.md](02-finance-domain.md) | Receivables finance basics, use cases, pain-point numbers | Finance |
| [03-agent-wallet.md](03-agent-wallet.md) | Agent wallet, policy guard, agent-injection guardrails | Agent AI engineer |
| [04-policy-ai.md](04-policy-ai.md) | Financing policy, credit risk model | Policy AI engineer |
| [05-ocr-ai.md](05-ocr-ai.md) | Invoice OCR, OCR injection, fraud detection | OCR AI engineer |

Service-level assistant prompts live next to the code: `services/<name>/CLAUDE.md`.

The interface spec is section 4 of `00-scope.md`; [`shared/schemas.py`](../shared/schemas.py) is the same contract as code. Contracts: [`../contracts/README.md`](../contracts/README.md). Team-wide rules: [`CLAUDE.md`](../CLAUDE.md).
