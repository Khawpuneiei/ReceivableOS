# Business size checklist: shaping ReceivableOS to win

> For P, Finance and the Policy AI eng (pitch pack owners). Numbers come from `docs/02-finance-domain.md` (sources P1–P17 in §7, demo numbers in §10, unit economics in §11). Anything marked **(est.)** is our assumption and must be said as one on stage.

## 0. The one rule

The official rules score **task completion 40%, security & compliance 30%, innovation & interaction 30%**, plus a 0–5 on-chain bonus. There is **no line for market size or revenue**. So the business case earns points only by:

- making the demo look like a real job a real customer pays for (task completion), and
- making the agent wallet idea look new and necessary (innovation).

Size the **story** big (a real, painful, sourced problem) and the **product** small (one customer, one invoice type, one flow that works live). A huge vision with a shaky demo loses to a narrow wedge that runs end to end.

---

## 1. Lock the wedge (decide once, write it on slide 1)

- [ ] **Customer in one sentence.** "Thai SME suppliers selling to large modern-trade retailers, invoices THB 100k–2m, 30–90 day terms." Siam Fresh Pack is the face of it.
- [ ] **One product.** Disclosed, with-recourse invoice factoring with buyer confirmation. Reverse factoring, export receivables and secondary trading are roadmap lines only.
- [ ] **One currency, one chain.** THB (tTHB on FISCO BCOS). Base Sepolia only as the bonus extra.
- [ ] **What we are not.** "We are not a lender. Financiers lend; ReceivableOS verifies the invoice and the SME's agent wallet takes the best offer inside the limits the SME set." This one line kills most licensing questions.
- [ ] **Why an agent, not a form.** The agent shops two lenders, picks within the mandate (70% advance, ≤ 12% APR, buyer PD ≤ 5%), executes, and settles on repayment. A human only steps in at THB 837,500 and above.

Done when all five lines appear, word for word, in the deck, the business plan and the README intro.

---

## 2. Size the market bottom-up (one slide, three numbers)

Judges trust a number they can check in their head. Use the sourced Thai gap as the serviceable market and show the math.

| Layer | Number | How we got it | Status |
|---|---|---|---|
| Context (not the headline) | Global factoring **EUR 4.04 tn**, APAC **~EUR 995 bn** (2025) | FCI (P16) | Sourced |
| **Serviceable gap** | **~THB 200 bn/yr** unmet Thai SME credit | BoT push THB 200 bn vs demand ~THB 400 bn (P6): 400 − 200 = 200 | Press report |
| Revenue pool at our take rate | **THB 600 m/yr** | 200 bn × 0.30% platform fee | Calc |
| **Year 1 pilot** | **THB 450 m** financed, **THB 1.35 m** fees | 1 anchor buyer, 50 suppliers × 1 invoice/month × THB 750k × 12 **(est.)** | Assumption |
| **Year 3 target** | **THB 18 bn** financed, **THB 54 m** fees | 1,000 SMEs × 2 invoices/month × THB 750k × 12 (§11 illustration) **(est.)** | Assumption |

- [ ] Say the Year 3 figure as a share of the gap: 18 / 200 = **9%**. That is ambitious, so pair it with how: about three anchor buyers' supplier bases, not "1% of a trillion".
- [ ] Never lead with EUR 4 tn. "1% of a huge market" is the most common hackathon red flag.
- [ ] Every number on the slide has its source ID (P6, P16) in small print, or **(est.)**.

---

## 3. Prove each side wants it (unit economics on one invoice)

Use the demo invoice (THB 749,000, 34-day tenor) so the slide matches the live screen.

| Who | What they get | Number |
|---|---|---|
| Seller | Cash now instead of in 34+ days | Receives **THB 516,705.14**; all-in cost 7,594.86 = **1.01%** of face (≈ 15.8% annualised) |
| Lender A | Pre-verified, fraud-checked, auto-settled deal | Fee 5,347.86 − funding cost 1,953.56 − expected loss 707.81 = **+THB 2,686.49** |
| ReceivableOS | Platform fee 0.30% of face | 2,247 − variable cost 150 **(est.)** = **+THB 2,097** contribution |

- [ ] **Break-even, said simply.** Fixed cost THB 1.5 m/month **(est.: team + infra)** ÷ 2,097 per invoice ≈ **716 invoices/month**, which is about **358 SMEs** at 2 invoices each. That sits between the Year 1 pilot and the Year 3 target, which is the story we want.
- [ ] **Why the SME pays ~16% a year.** Banks refuse 60–70% of Thai SMEs (P5); the alternatives are paying suppliers late or informal lending **(est.: costlier)**, and the facility costs nothing when unused.
- [ ] **Why the lender joins.** Double financing is the reason lenders avoid SMEs (P17); our registry makes a second financing of the same invoice revert on chain.

---

## 4. Tie the business case to each scoring line

| Criterion | What the business story must show | Proof on screen |
|---|---|---|
| **Task completion 40%** | The full job a paying customer needs: upload → check → decide → fund → repay | Live run with the exact numbers above (749,000 / 524,300 / 5,347.86 / 516,705.14) and ≥ 5 real FISCO BCOS tx hashes |
| **Security & compliance 30%** | Every risk the business model creates has a control | Fraud → `fraud_score` reject; double financing → registry revert; agent overspend → guard blocks (red BLOCKED row); big amount → human approval at ≥ THB 837,500; no PII on chain; KYB and PDPA named as production steps |
| **Innovation & interaction 30%** | Why an **agent wallet** is the new part, not just "AI + blockchain" | SME writes the mandate in plain language, sees the compiled JSON, watches the agent compare lenders and explain its pick |
| **Bonus 0–5** | On-chain exploration beyond the minimum | Optional Base Sepolia mirror after Oct 12 |

- [ ] Each row has one slide moment and one sentence in the deck notes.
- [ ] The theme is "AI as a Financial Participant". Say those words once, on the solution slide.
- [ ] FISCO BCOS is WeBank's chain and the reviewers are WeBank experts. Supply-chain finance is a well-known FISCO BCOS use case **(inferred: check the FISCO BCOS case list before saying it on stage)**.

---

## 5. Fit it into 10 minutes

| # | Slide | Time |
|---|---|---|
| 1 | Problem: SMEs wait 65 days and get refused (P5, P8), lenders fear double financing (P17) | 0:45 |
| 2 | Wedge and solution (section 1 lines) | 0:45 |
| 3–5 | **Live demo**: happy path, one blocked tx, one duplicate invoice | 4:00 |
| 6 | Security design: six guard layers, human approval, known limits | 1:30 |
| 7 | Market and unit economics (sections 2 and 3, one slide) | 1:00 |
| 8 | Roadmap: pilot with one financier → e-Tax invoices → NITMX TDR link → licensed THB rail | 0:30 |
| 9 | Team and ask | 0:30 |
| | Buffer | 1:00 |

- [ ] Business content gets **one slide and one minute**. The demo gets four.
- [ ] Rehearsed under 10:00 twice (scope doc §6.1).

---

## 6. Cut list (signs the idea is sized too big)

- [ ] No DeFi liquidity pools, token sale, secondary trading of receivables or cross-border flows in the build. One roadmap line at most.
- [ ] No five-year revenue chart. Year 1 and Year 3 with stated assumptions are enough.
- [ ] No "we lend" or "we hold customer money".
- [ ] No number that is not in `docs/02` §7 or marked **(est.)**.
- [ ] No feature on a slide that the demo cannot show. If it is not built, it says "roadmap".

---

## 7. Q&A cards (Finance owns, P checks)

Have a one-breath answer for each:

1. **"Who is liable if the agent makes a bad deal?"** The SME set the mandate; the guard enforces it in code; anything at or above THB 837,500 waits for a human.
2. **"Why blockchain and not a database?"** Several lenders need one shared record of which invoice is already financed, and no single lender should own it. Thai banks built NITMX TDR for the same reason (P17); we complement it.
3. **"Are you a lender? Do you need a licence?"** No. Financiers lend. Production needs KYB, PDPA compliance and a licensed THB settlement rail; the MVP uses simulated tTHB.
4. **"What if the buyer doesn't pay?"** With-recourse: the seller owes it; the 30% reserve (THB 224,700) absorbs the first loss.
5. **"How did you get the 0.9% fee?"** Cost of funds + expected loss + margin, priced off buyer PD (`docs/07` shows the math).
6. **"Why now?"** Thailand caps large buyers' credit terms to SMEs at 45 days from 2 Nov 2026 (P9), and SME lending has shrunk for 16 quarters (P5).

---

## 8. Owners and deadlines (Bangkok time)

| When | What | Owner |
|---|---|---|
| Sat 11 Oct 10:00 | Wedge lines (section 1) and demo numbers signed off | P + Finance |
| Sat 11 Oct 20:00 | Problem and market slide (sections 2 and 5, slides 1 and 7) | Finance |
| Sat 11 Oct 22:00 | Business-plan draft, 2–3 pages, using `docs/02` §11.1 | Finance |
| Sun 12 Oct 10:00 | Business slide + Q&A cards (section 7) | Finance, P checks |
| Sun 12 Oct 12:00–18:00 | Deck first draft, section 4 mapped slide by slide | P + Policy AI eng + Finance |
| Sat 18 Oct | First full submission uploaded | P |
| Mon 20 Oct 18:00 | Final update (deadline 22:59) | P |
