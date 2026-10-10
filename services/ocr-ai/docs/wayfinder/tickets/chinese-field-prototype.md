---
name: Prototype Simplified Chinese field anchors and normalization
label: wayfinder:prototype
parent: ../map.md
status: superseded
assignee: codex
blocked_by: []
---

## Question

Can a source-grounded Simplified Chinese adapter resolve supplier/buyer roles, invoice/PO references, payable totals and native date/currency notation while retaining explicit unsupported cases?

Test native-script names, mixed Chinese/English labels, subtotal versus tax-inclusive total, ambiguous yuan symbols and independently scoped identifiers. Keep Qwen candidates separate from authoritative evidence; country/script metadata alone cannot grant support. Traditional Chinese and other unseen forms must be explicitly excluded or separately evaluated.

Resolution requires a disposable prototype, positive/negative cases with source locations, independent language-review needs and a promotion decision. The current 0/112 header result identifies the missing live mapping, not failure of every Chinese recognition model.

The latest user-authorized [architecture task](architecture-upgrade.md) supersedes this spike for exact aliases with ISO financial forms and mandatory experimental review. [Measured results](../../ARCHITECTURE_VALIDATION.md) cover generated sources; native dates/numerals, yuan-symbol ambiguity and wider language review remain excluded/unresolved rather than guessed.
