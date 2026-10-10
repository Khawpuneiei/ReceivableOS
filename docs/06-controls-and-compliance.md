# 06 — Controls and Compliance (PM brief)

> **For P (PM, integration, pitch).** Five concerns a judge or a bank partner will poke at: spending limits and mandates, human approval and dual control, the audit log, KYC/AML, and data privacy. For each: what can go wrong in *this* product, what you will be asked, what the state of the art is, the setting we recommend for the demo, and the one line you say on stage.
>
> Status: **v0.1, 2026-10-10.** Builds on the wallet mechanics in `services/agent-wallet/CLAUDE.md` (and `docs/03-agent-wallet.md` once it lands), the mandate in `docs/02-finance-domain.md` §10, and the attack cases A1–A6 in `docs/01-architecture.md` §3.6. This file does not redefine those mechanics; it says which settings to pick and how to talk about them.
> **Feeds the submission.** The official security self-assessment (permission tiers + known-risk list, in English) lives in `pitch/security-self-assessment.md`, owned by the Agent Wallet eng and P (`docs/01` §2.1). Lift from here: key roles and dual control (§2.1, §2.4), mandate limits (§1.4), and known risks (§1.1, §1.5, §2.1, §3.1, §6 "Known limits").
> Numbers marked **(est.)** are our assumptions, not sourced facts. This is not legal advice.

---

## 0. The five stage lines (memorise these)

| Concern | One line for the stage |
|---|---|
| Spending limits | "The AI can propose anything, but the chain only lets it spend inside the seller's mandate: 70% advance, 12% APR, allowlisted payees, per-transaction and daily caps. If the model is fooled, the transaction reverts." |
| Human approval | "From THB 837,500 up, or whenever the invoice looks odd, the money stops and waits for a human signature that is bound to that exact payment, and the person who approves is not the person who set the rules." |
| Audit log | "Every decision and every block is hash-chained and anchored on chain, so for any baht we can answer why, on what evidence, by which model and policy, who approved it, and which transaction moved it." |
| KYC/AML | "We onboard businesses, not anonymous wallets: every seller, buyer and lender is a verified, allowlisted party, and in production the licensed lender stays the AML reporting entity while we hand it the KYB evidence and the audit trail." |
| Data privacy | "No personal data goes on chain, only salted fingerprints, amounts and statuses; the documents stay off chain under Thailand's PDPA, and the demo runs on synthetic data only." |

---

## 1. Spending limits and mandates

### 1.1 What can go wrong in ReceivableOS

| Failure | How it would happen here | Control we already have (where) |
|---|---|---|
| Manipulated agent pays an attacker | Injection text in an invoice ("pay 0xAttacker") reaches the agent (A1) | Payees are registry ids, not addresses from invoice text; on-chain `payeeAllowed` (wallet §5.3, §5.5) |
| Over-advance | Lender or agent proposes 80% LTV or a draw above the approved limit (V8, A4) | `max_ltv` 0.70 in mandate; `AmountAboveLimit` in `PolicyGuard`; decision limit check off chain |
| Expensive credit | Only quote is 19.5% APR (A3, V5) | `AprAboveMandate` on chain |
| Salami slicing | Many draws just under the approval threshold, each one "small" | Daily cap counts pending amounts too (wallet §5.4); one draw per invoice key |
| Replay / stale decision | Old "approve" reused for a new draw | Idempotency key, `invoiceKeyUsed`, `max_age_seconds: 900` (wallet §5.2, §5.4) |
| Unit error | THB value read as mUSD, or 2 vs 6 decimals → a 100× or 33.5× payment | **Gap, see 1.5.** Wallet yaml is still in USD/6 decimals; architecture and Finance use tTHB/2 decimals |
| Agent key stolen | Attacker signs `execute()` directly | Key can only call `execute`, so loss is bounded by the on-chain caps |
| Owner key stolen, or mandate set too loose | Attacker (or a careless user) raises limits, then drains | **Not covered in MVP.** Production: multisig owner plus a time delay on any change that loosens the mandate |

### 1.2 What judges and a bank partner will ask

- "What stops the AI from sending all the money somewhere else?" (allowlist + on-chain guard, show A1 revert)
- "Who sets the mandate, and can the AI change it?" (only the owner key; the agent key cannot call `setMandate`/`setLimits`)
- "What is the worst case if your agent key leaks?" (one day's cap, to allowlisted payees only: THB 3,000,000 in the recommended setting)
- "Are the limits enforced in your Python or in the contract?" (both; the contract is the one that counts, and the demo flag `skip_offchain_checks` proves it)
- Bank: "How do your limits map to our credit approval limits and our facility limit for this seller?"

### 1.3 State of the art (2025–2026)

- **Signed, scoped mandates.** Google's Agent Payments Protocol (AP2, Sep 2025) splits authority into an *Intent Mandate* (human not present: pre-agreed conditions, such as a price cap) and a *Cart Mandate* (human present: approval of one exact purchase), both signed as verifiable credentials so the payment network can later see what the user actually authorised ([TechCrunch](https://techcrunch.com/2025/09/16/google-launches-new-protocol-for-agent-driven-purchases), [Fintech Brainfood](https://www.fintechbrainfood.com/p/ap2-explained)). Our JSON mandate is an Intent Mandate; the human-approval path is a Cart Mandate.
- **Card networks** ship agent-specific tokens with spending controls (Visa Intelligent Commerce, Mastercard Agent Pay, 2025) ([Digital Commerce 360](https://www.digitalcommerce360.com/2025/05/06/visa-mastercard-ai-agentic-commerce/)).
- **Crypto agent wallets** put limits outside the model: Coinbase *Agentic Wallets* (Feb 2026) offer spending limits and session-duration limits, with keys held in an enclave and never passed to the LLM ([ForkLog](https://forklog.com/en/coinbase-unveils-wallet-infrastructure-for-ai-agents/)). Practitioner guidance for x402 agent payments lists per-transaction caps, daily and per-endpoint budgets, allowlists, atomic budget reservation, duplicate detection and a circuit breaker after repeated violations ([dev.to](https://dev.to/l_x_1/securing-the-x402-protocol-why-autonomous-agent-payments-need-spending-controls-a90)).
- **Smart accounts** (Safe modules, ERC-4337 session keys) are the EVM production path; scope already lists them as roadmap because they are not native to FISCO BCOS.

Proof point for the pitch: the wallet's red-team eval set has 39 attack cases, reported as "N attacks, 0 unauthorized payments" (wallet brief §7.4); quote the final number from its run.

Takeaway: our design (limits enforced in a contract the model cannot touch, payee allowlist, budget reserved before transfer, pause switch) matches what the industry converged on. What we lack is a signed mandate credential and a delay on loosening it; both are roadmap lines, not demo work.

### 1.4 Recommended demo setting (matches the Finance mandate)

| Parameter | Demo value | Source / reason |
|---|---|---|
| `max_ltv` | 0.70 | Finance mandate (`docs/02` §10) |
| `max_apr` | 12% (1200 bps) | Finance mandate |
| `max_predicted_default` | 5% | Finance mandate (checked by Policy AI, not on chain) |
| `approval_threshold` | **THB 837,500, at or above** | Finance `human_review_above_thb` (= USD 25,000 × 33.5, est. rate); wallet env default (PR #8) uses `>=` |
| `per_tx_max` | **THB 1,500,000 (est.)** | Above the threshold so a large approved draw can still go through; Finance to confirm |
| `daily_max` | **THB 3,000,000 (est.)** | Equals the seller's facility limit, so one bad day can never exceed the facility |
| Payee allowlist | Siam Fresh Pack (disbursement), Andaman Factoring and Isan Growth (repayment), platform fee address | `docs/02` §10 parties |
| Settlement asset | tTHB, 2 decimals | Architecture default |
| Decision max age | 900 s | Wallet default |
| Pause | Owner or approver can pause; only owner unpauses | Wallet default (A6) |

Happy path: the THB 524,300 advance is under 837,500, so it executes without a human, which keeps the main demo fast.

### 1.5 Open items for P (owned by other threads; flag, don't fix here)

1. **Currency and decimals.** `services/agent-wallet/CLAUDE.md` §5.2 still has USD placeholders (`per_tx_max 20000`, `daily_max 50000`, `approval_threshold 10000`, mUSD with 6 decimals). Architecture and Finance use tTHB with 2 decimals. Ask the Agent AI eng to switch the yaml and the deploy script to the THB values above, and add one unit test that a THB 524,300.00 request becomes exactly `52430000` token units.
2. **"Above" versus "at or above".** Settled in the wallet PR (#8): review at or above 837,500 (`>=`). Finance's mandate text says "above"; ask Finance to reword it to "at or above" so the UI, mandate and contract read the same.
3. **Facility limit on chain.** Nothing on chain tracks total outstanding per seller (THB 3,000,000). The daily cap is a proxy for the demo; say "outstanding-exposure limit" is roadmap.

---

## 2. Human approval and dual control

### 2.1 What can go wrong

| Failure | Why it matters here | Mitigation |
|---|---|---|
| Rubber-stamping | The approver clicks "approve" on whatever the AI summarised | Approval card shows raw fields (payee registry name, amount, APR, LTV, decision hash, flags), not an LLM-written summary |
| The AI writes the approval request | Injection text could make the summary read "safe" | The card is rendered from validated fields only; the invoice memo is shown as untrusted text, clearly labelled |
| Approve one thing, execute another | Approver sees 900k to Lender A, chain pays something else | The contract stores the pending payment (`to`, `amount`, `invoiceKey`, `decisionHash`) at proposal time; `approve(id)` (called via `POST /wallet/confirm/{tx_id}`) can only release that exact record |
| Same person sets the rules and approves | No segregation of duties; one compromised laptop does both | Different keys and different people for owner and approver (see 2.4) |
| Risk-oracle key held by the wallet service | In the MVP the wallet service holds both the agent key and the risk-oracle key (`docs/01` §5.5 roles), so a compromised wallet service could approve its own receivable | Say it on stage as a known MVP shortcut; production moves the oracle key to the Policy service (or an HSM) and has Policy sign decisions (wallet §6.4 item 1) |
| Approval never comes | Money stuck, SME waits | Pending approvals expire after 24 h with `APPROVAL_EXPIRED` (wallet §5.4) |

### 2.2 What they will ask

- "When does a human have to step in, and is it only about the amount?"
- "Can the AI approve its own transaction?"
- "Who are your approvers, and what do they actually see?"
- Bank: "Does this fit our four-eyes rule and our delegated credit authority?"
- Regulator-minded judge: "How does this meet human-oversight expectations for AI in lending?"

### 2.3 State of the art and regulatory expectation

- **Bank of Thailand AI Risk Management Guidelines** (final, 12 Sep 2025) apply to banks and payment providers and say human oversight must be embedded in decision-making, scaled to risk and impact, especially for uses like loan approval; customers should be told when they deal with AI and be able to reach a human ([Tilleke & Gibbins](https://www.tilleke.com/insights/thailand-issues-ai-risk-management-guidelines-for-financial-service-providers/)). Our bank or lender partner would be the regulated firm; our design should make their compliance easy.
- **EU AI Act** (global reference) lists AI creditworthiness assessment of natural persons as high-risk and requires human oversight (Art. 14) and automatic event logging (Art. 12) ([EU AI Act Service Desk, Art. 12](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-12)). Our borrowers are companies, so it would not apply directly, but it is the benchmark judges know.
- **Industry pattern:** risk-based escalation (amount *and* anomaly triggers), approval bound to a hash of the exact payment, M-of-N signers, expiry, and a kill switch. AP2's Cart Mandate is the same idea for consumer payments.

### 2.4 Recommended demo setting

| Item | Demo value |
|---|---|
| Amount trigger | Advance ≥ THB 837,500 → `pending_approval`; approver confirms via `POST /wallet/confirm/{tx_id}` |
| Risk triggers (approve becomes "needs human") | `decision == review`, any `injection_flags`, `fraud_score >= 0.5` (wallet §5.2 `escalate_to_human_if`) |
| Approvers | **1 of 1, but the approver is the Finance teammate, not P.** P holds the owner key (sets the mandate, unpauses); Finance holds `approver_1` (approves, can pause) |
| Production story | 2-of-3 approvers, hardware keys, owner as multisig with a delay on loosening limits |
| Expiry | 24 h |
| On-stage moment (optional, 30 s) | A second invoice from the same seller, face THB 1,400,000 → advance THB 980,000 (est. scenario) → card goes amber "waiting for human" → Finance teammate approves → tx hash appears. This shows the approval path without touching the happy path |

If the demo has no time for the approval moment, show the `pending_approval` status in the transaction list and say the line.

---

## 3. Audit log

### 3.1 What can go wrong

| Failure | Detail | Mitigation |
|---|---|---|
| Log edited after the fact | A plain hash chain (wallet §5.7) detects edits only if someone kept an earlier hash; whoever controls the file can rewrite the whole chain | Anchor the chain head on chain (`anchorAudit`) so history before the anchor is frozen |
| Gap between anchors | Wallet anchors every 10 entries; the last few events before a crash are unanchored | **Anchor at the end of every flow** (after `SETTLED`, `BLOCKED`, `REJECTED`), not only every 10 entries |
| Two logs that disagree | Orchestrator log and wallet log each record part of the flow | One `flow_id` in every entry of both logs; the UI's audit view merges them by `flow_id` and shows both `verified` flags |
| Log leaks data | Raw invoice text or names copied into the log | Log ids, hashes, amounts, codes and versions only; never invoice text or personal names |
| Log explains nothing | Hash of a decision without its inputs is not an explanation | Store `decision_hash`, `reasons`, `model_version`, `policy_version`, evidence hashes; keep the inputs off chain so the hash can be re-computed on request |

### 3.2 What they will ask

- "Show me the audit trail for this payment." (be ready to click into it live)
- "How do I know you didn't edit the log after the demo?"
- "Why did the AI decide this, and could you reproduce it?"
- Bank: "How long do you keep records, and can our auditor verify them independently?"

### 3.3 State of the art

- **Tamper-evident logs** use Merkle trees with signed tree heads and inclusion/consistency proofs, as in Certificate Transparency ([RFC 9162](https://www.rfc-editor.org/rfc/rfc9162)). Anchoring the root in a public or consortium ledger is the blockchain variant of the same idea.
- **AI logging** is now a regulatory expectation: EU AI Act Art. 12 requires automatic, lifetime logging for high-risk AI; BoT's 2025 guideline asks for documentation of model inputs, outputs and parameters so outcomes can be explained ([Tilleke & Gibbins](https://www.tilleke.com/insights/thailand-issues-ai-risk-management-guidelines-for-financial-service-providers/)).
- **Retention:** Thai digital-asset operators must keep travel-rule records for at least 5 years ([Crowdfund Insider, Sep 2026](https://www.crowdfundinsider.com/2026/09/306828-thailands-securities-regulator-finalizes-crypto-travel-rule-effective-february-2027/)); AML record keeping for banks is of the same order (est., verify against the Anti-Money Laundering Act before quoting a number).

### 3.4 Recommended demo setting

- Keep the wallet's hash-chained JSONL (wallet §5.7); add `flow_id` to every entry in both services.
- Anchor on chain at the end of each flow and at demo end; show the anchor tx hash in the audit panel.
- Audit panel for one flow shows, in order: OCR result hash and flags → decision (`decision`, `reasons`, `model_version`, `policy_version`, `decision_hash`) → each guard check → approval (who, when) or block (code) → tx hash → anchor tx hash → `verified: true`.
- Live trick for Q&A: edit one byte in the local log, refresh, and show `verified: false` (est. 10 minutes of work for the Agent AI eng; worth it).

---

## 4. KYC / AML

### 4.1 What can go wrong in this product

- **Fake or shell seller** invoices a fake buyer to pull cash out (fraud, possibly laundering).
- **Related-party round-tripping**: seller and buyer are the same group (`docs/02` §5).
- **Sanctioned or high-risk party** as seller, buyer or lender.
- **Mule accounts**: the payee address or bank account belongs to someone else.
- **Token as a laundering rail**: if tokenised receivables or tTHB could move to unknown wallets, they become a value-transfer channel.

### 4.2 What they will ask

- "Who is your customer, and who does KYC?"
- "Are you a reporting entity under Thai AML law?"
- "Can a token go to an anonymous wallet?"
- "Do you need an SEC licence for the receivable token?"

### 4.3 Who regulates what (Thailand, plus the global reference)

| Body / law | Relevance to ReceivableOS | Source |
|---|---|---|
| **AMLO**, Anti-Money Laundering Act B.E. 2542 (1999) | Reporting entities include banks, payment businesses, personal-loan operators, securities firms and **digital asset businesses**. Non-bank factoring is not on the published list we found (verify with counsel). In production our bank or lender partner is the reporting entity; we supply KYB evidence and screening. | [Baker McKenzie AML/CFT guide](https://www.bakermckenzie.com/en/insight/publications/guides/complete-guide-aml-cft-thailand) |
| **SEC Thailand**, Emergency Decree on Digital Asset Businesses B.E. 2561 (2018) | If a receivable token were offered to investors it could be an investment token and need SEC approval. Our tokens are simulated, on a permissioned chain, not offered to anyone. The SEC's crypto travel rule (Notification Sor Thor. 9/2026) takes effect **27 Feb 2027**: all transfers carry originator and beneficiary data, extra data above THB 30,000, self-hosted wallets must be proven to belong to the customer, records kept 5 years. | [Crowdfund Insider](https://www.crowdfundinsider.com/2026/09/306828-thailands-securities-regulator-finalizes-crypto-travel-rule-effective-february-2027/); [Baker McKenzie 2025 round-up](https://www.bakermckenzie.com/en/insight/publications/alerts/2025/12/thailand-digital-asset-regulatory-round-up-2025-10-key-developments) |
| **SEC + operators' association**, mule-account rules (Aug 2025) | Operators must treat flagged mule-account owners as high risk, refuse onboarding and suspend transfers. Same idea as our payee allowlist. | [Baker McKenzie 2025 round-up](https://www.bakermckenzie.com/en/insight/publications/alerts/2025/12/thailand-digital-asset-regulatory-round-up-2025-10-key-developments) |
| **Bank of Thailand** | Supervises banks and payment providers (our partner), issued the 2025 AI guideline, runs the digital factoring platform that checks invoices against double financing, and runs the Programmable Payment (THB stablecoin) sandbox, which is the realistic path for a real tTHB. | [Chambers 2025](https://practiceguides.chambers.com/practice-guides/banking-finance-2025/thailand/trends-and-developments); [Baker McKenzie 2025 round-up](https://www.bakermckenzie.com/en/insight/publications/alerts/2025/12/thailand-digital-asset-regulatory-round-up-2025-10-key-developments) |
| **FATF** (global) | R.10 customer due diligence, R.15 virtual assets, R.16 wire transfers / travel rule. R.16 was revised in June 2025 (beneficiary country and town, legal-person identifiers such as LEI above the threshold, beneficiary name checks), with members expected to implement by end-2030. | [21 Analytics](https://www.21analytics.co/blog/fatf-recommendation-16-updated/) |

### 4.4 State of the art

KYB for companies (registry check, directors, ultimate beneficial owners, sanctions and PEP screening), ongoing monitoring with re-screening on expiry, transaction monitoring (KYT) on the chain side, and portable credentials (verifiable credentials or Thailand's NDID for e-KYC) so a seller verifies once and reuses the result. Agent payment schemes put the verified identity in the credential, not in the agent.

### 4.5 In scope for the demo vs future work

| In the demo (P owns the KYC mock in the orchestrator) | Stated as future work |
|---|---|
| Mock KYB credential per party: `kyc_valid`, `kyc_expiry` (Policy AI already reads them; A5 / scenario 7 rejects an expired one) | Real KYB provider, DBD registry lookup, UBO and director checks |
| Every payee is a registered, allowlisted party; no transfer to an address that is not in the registry | Sanctions / PEP / mule-account list screening at onboarding and before each payment |
| One mock sanctions check: a hard-coded deny list of one fictional name, shown blocked (optional, est. 20 min) | Travel-rule data on transfers (Thai SEC rule from Feb 2027) |
| tTHB is a simulated token on a permissioned chain, only allowlisted addresses hold it | Licensed THB rail (bank account or BoT-sandbox stablecoin) |
| Buyer confirmation credential (already in the scenario) | Link to the BoT digital factoring platform / NITMX registry before registering on chain |

**Stage line:** "We onboard businesses, not anonymous wallets: every party is verified and allowlisted, and in production the licensed lender remains the AML reporting entity while ReceivableOS gives it the KYB evidence and a tamper-evident trail."

---

## 5. Data privacy

### 5.1 What can go wrong in this product

| Risk | Detail | Mitigation |
|---|---|---|
| Personal data in invoices | Invoices carry contact names, signatures, phone numbers, and sole-proprietor names (a sole trader's tax ID is a personal ID number). These are personal data under PDPA; company data is not, but it is commercially confidential | Extract only fields we need; never log raw text; synthetic data in the demo |
| Guessable fingerprints on chain | The invoice fingerprint (seller tax ID + invoice no. + buyer tax ID + amount + date, `docs/02` §5) has low entropy. A plain hash can be brute-forced to reveal who trades with whom and for how much | Use a **keyed hash** (HMAC with a network secret) for the fingerprint, and keep the chain permissioned. `doc_hash` of the full file is fine (high entropy) |
| "Right to erasure" vs an immutable chain | PDPA gives data subjects rights to deletion | Nothing personal on chain; delete the off-chain record and its key, and the on-chain hash points to nothing (crypto-shredding) |
| Invoices sent to a foreign LLM API | Sending personal data abroad is a cross-border transfer; the destination must have adequate protection or another safeguard must apply | Demo: synthetic data only. Production: data processing agreement, regional hosting or a self-hosted model, redact personal fields before the LLM step |
| Processor failures | PDPC has fined both controllers and their processors, including for missing data-processing agreements | Written agreements with OCR/LLM/cloud vendors in production |
| Breach | Leaked invoices reveal SME customers and margins | 72-hour notification duty to the PDPC; least-privilege access, encryption at rest |

### 5.2 What they will ask

- "What do you put on the blockchain?"
- "Is any personal data in your training set?"
- "Do invoices leave Thailand when your AI reads them?"
- "How do you delete a customer's data if the chain is immutable?"
- Shenzhen judges may ask about China's own data rules (PIPL) if the product were deployed there; answer that a China deployment would need a local data review and is out of scope.

### 5.3 The law

- **Thailand Personal Data Protection Act B.E. 2562 (2019), PDPA**, enforced by the **Personal Data Protection Committee (PDPC)**. Administrative fines up to THB 5 million per offence, criminal penalties up to 1 year and THB 1 million, civil damages; breach notification within 72 hours; DPO appointment where required; cross-border transfers need an adequate destination or an approved safeguard ([Legal 500](https://www.legal500.com/developments/thought-leadership/thailands-personal-data-protection-overview-and-updates)).
- **Enforcement is real now.** PDPC announced eight fines on 1 Aug 2025, up to THB 7 million for one retailer, including fines on processors and for failing to appoint a DPO or notify a breach ([Tilleke & Gibbins](https://www.tilleke.com/insights/more-than-a-warning-eight-serious-fines-imposed-in-thai-data-protection-cases)).
- **BoT AI guideline (2025)** also asks for data-leakage prevention and compliance with personal data law in AI systems ([Tilleke & Gibbins](https://www.tilleke.com/insights/thailand-issues-ai-risk-management-guidelines-for-financial-service-providers/)).

### 5.4 In scope for the demo vs future work

| In the demo | Stated as future work |
|---|---|
| Synthetic, fictional parties and invoices only (`docs/02` §10); no real PII anywhere (scope rule) | DPIA, DPO, privacy notice and consent flows |
| On chain: `doc_hash`, keyed invoice fingerprint, amounts, statuses, decision hash, versions. Nothing else | Redaction of personal fields before any external LLM call |
| Audit log holds ids, hashes and codes, not invoice text | Data processing agreements, regional hosting, retention schedule |
| Permissioned FISCO BCOS consortium chain (or the mock ledger) | Selective disclosure / zero-knowledge proofs for lenders (roadmap) |

**Stage line:** "No personal data goes on chain, only salted fingerprints, amounts and statuses; documents stay off chain under Thailand's PDPA, and today's demo runs only on synthetic data."

---

## 6. Checklist for P before the Oct 12 freeze

- [ ] Wallet yaml and deploy script in tTHB with the 1.4 values; unit test for decimals (Agent AI eng)
- [ ] Finance mandate text reworded to "at or above 837,500" to match the wallet (`>=`), and Finance confirms the 1.5m / 3m caps
- [ ] Approver key held by the Finance teammate, owner key by P
- [ ] `flow_id` in every audit entry; anchor at end of each flow; audit panel shows `verified`
- [ ] Invoice fingerprint uses a keyed hash (OCR AI + Agent AI eng)
- [ ] KYC mock in the orchestrator has `kyc_valid`, `kyc_expiry` per party; A5 shows a reject
- [ ] Optional: large-invoice approval moment (2.4) and log-tamper trick (3.4)
- [ ] Pitch deck has one "Controls" slide with the five lines from §0 and one "Known limits" line: risk-oracle key in the wallet service, no outstanding-exposure limit on chain, mock KYB, simulated THB

---

## 7. Sources

- Google AP2: [TechCrunch, 16 Sep 2025](https://techcrunch.com/2025/09/16/google-launches-new-protocol-for-agent-driven-purchases); [Fintech Brainfood, AP2 explained](https://www.fintechbrainfood.com/p/ap2-explained)
- Visa / Mastercard agentic payments: [Digital Commerce 360, 6 May 2025](https://www.digitalcommerce360.com/2025/05/06/visa-mastercard-ai-agentic-commerce/)
- Coinbase Agentic Wallets: [ForkLog, 12 Feb 2026](https://forklog.com/en/coinbase-unveils-wallet-infrastructure-for-ai-agents/)
- x402 spending controls: [dev.to](https://dev.to/l_x_1/securing-the-x402-protocol-why-autonomous-agent-payments-need-spending-controls-a90)
- BoT AI Risk Management Guidelines: [Tilleke & Gibbins](https://www.tilleke.com/insights/thailand-issues-ai-risk-management-guidelines-for-financial-service-providers/)
- EU AI Act Art. 12: [AI Act Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-12)
- Certificate Transparency: [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162)
- Thai AML reporting entities: [Baker McKenzie AML/CFT guide](https://www.bakermckenzie.com/en/insight/publications/guides/complete-guide-aml-cft-thailand)
- Thai digital-asset developments 2025: [Baker McKenzie, Dec 2025](https://www.bakermckenzie.com/en/insight/publications/alerts/2025/12/thailand-digital-asset-regulatory-round-up-2025-10-key-developments)
- Thai SEC travel rule: [Crowdfund Insider, 6 Sep 2026](https://www.crowdfundinsider.com/2026/09/306828-thailands-securities-regulator-finalizes-crypto-travel-rule-effective-february-2027/)
- FATF R.16 revision: [21 Analytics](https://www.21analytics.co/blog/fatf-recommendation-16-updated/)
- Thai factoring, assignment law, BoT digital factoring: [Chambers Banking & Finance 2025, Thailand](https://practiceguides.chambers.com/practice-guides/banking-finance-2025/thailand/trends-and-developments)
- PDPA overview: [Legal 500](https://www.legal500.com/developments/thought-leadership/thailands-personal-data-protection-overview-and-updates)
- PDPA enforcement: [Tilleke & Gibbins, Aug 2025](https://www.tilleke.com/insights/more-than-a-warning-eight-serious-fines-imposed-in-thai-data-protection-cases)
