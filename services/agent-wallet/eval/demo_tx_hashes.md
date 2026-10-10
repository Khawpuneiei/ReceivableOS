# Demo transactions (mock ledger)

Run on 2026-10-11. Every hash below is a MOCK hash (prefix `mock:`), not a chain hash.

| step | status | block reason | tx_id | chain_ref |
|---|---|---|---|---|
| register inv_happy | executed |  | tx_c36a6430490a431f | mock:0x446f406b3f6ac3716e4f207e1c0acd9bc8b7b3a2c5c6dcbb5ac2a6326a2400ed |
| approve (TX-2) inv_happy | executed |  | tx_8c551b2c57834192 | mock:0x0db24bd50df0c723534394a678477b1da9e0d7772f727faeac8af1a25e27372b |
| execute draw (TX-4) inv_happy | executed |  | tx_c8a1c9fb84fb482e | mock:0x41dd436bc5f02b9b61911a3b657432bc2fabbbcda9c097117a2df1d4f274f1f2 |
| settle, buyer paid 749,000 (TX-5) | executed |  | tx_4e4b3bf1d4d54976 | mock:0xc6e125e221dd41f74abc98e2b7c64c6b2678eeaff9ce842fa799a46091a0c74b |
| execute 980,000 (above 837,500) | pending_approval |  | tx_85594ed713c64450 | mock:0x9c4dc4137acf14d9a0d18f6bada56e6e0bca4154097b766925d32302ac48d0ed |
| approver confirms | executed |  | tx_9a4ede6f3f4f4cc3 | mock:0x709a663d2a17bc92c28d4a824ee62f1d49e5b913a101710334d1c80a1af90fe0 |
| draw at 19.5% APR (L3) | blocked | AprAboveMandate | tx_5ebf85da834f426b | none (off-chain) |
| draw 600,000 above limit (L3) | blocked | AmountAboveLimit | tx_1a1a04f802d047a6 | none (off-chain) |
| 19.5% APR, bypass (on-chain revert) | blocked | AprAboveMandate | tx_68c87e0543c94859 | mock:0xbe82381c4132fc2092daca3e524693f318de3e8e7b44a362b73f6acc9dd1ea2f |
| 600,000 above limit, bypass (revert) | blocked | AmountAboveLimit | tx_afd20c10489645d7 | mock:0x15675aae740867b8c0a88fb5c37b85457aecc4be46c714bc49cb8aaae07dfeb4 |
| forced draw on injected invoice, no TX-2 | blocked | NotApproved | tx_1499df745933409a | none (off-chain) |
| re-saved PDF registered again (A2) | blocked | DuplicateReceivable | tx_f93ec065eed44cae | mock:0xc0eeebafd2d01dc97781c5ab9030d399d37e190f94a06aa5dc792b64d43d98d1 |
| pause | executed |  | tx_0769f358c0174691 | mock:0x3f80c68859a765bba8f41d6d12654bb7bd9ad21bfeda0672639d1b6007c9d3ed |
| draw while paused | blocked | Paused | tx_77ddd9cfa6314848 | none (off-chain) |
| unpause (owner) | executed |  | tx_1b409409ea544375 | mock:0x86be787d3e5675a57b4e2db19bb1878d68cbf9ec8ab16cca474898f87991a4a4 |
