# Demo transactions (fisco ledger)

Run on 2026-10-11, run id 20261011073405. Every hash below is a fisco transaction hash. Receipts go to FISCO_RECEIPTS_DIR.

| step | status | block reason | tx_id | chain_ref |
|---|---|---|---|---|
| register inv_happy | executed |  | tx_aece8c7f51054d31 | 0x3530f192bc2380189358feadf06dc1f210a71cb4db1966116319967f8a1e2668 |
| approve (TX-2) inv_happy | executed |  | tx_fe0c34d564a04b09 | 0x2d9398c45b83442a8de9810472a43666b474debea15692e08296463cd7cbbab8 |
| execute draw (TX-4) inv_happy | executed |  | tx_9ae4b95cc51f44a3 | 0x5ed8efebd2be9df6f3b334bc0a6e028db3ff3aba5ab5891b6a9bab981c1a8b74 |
| settle, buyer paid 749,000 (TX-5) | executed |  | tx_de84d5b913bc4ed4 | 0x48f1b84e727b5df9db4c8ab3d46aee556c190fc84383a7ceceabf6ab85bf4ef8 |
| execute 980,000 (above 837,500) | pending_approval |  | tx_4bfc636caf4b4ce4 | 0x950c8ef667ea7ee024cf8d42d76d7238f560881e46e7e9ceecc5466a1e25c9b2 |
| approver confirms | executed |  | tx_309a482dbc2a4bda | 0x3098c9a7c8a1d33999db4f6a21ac1c70a55a1ed1e13b7174d18fb0c7287af5f7 |
| draw at 19.5% APR (L3) | blocked | AprAboveMandate | tx_a748ab63423f4e9c | none (off-chain) |
| draw 600,000 above limit (L3) | blocked | AmountAboveLimit | tx_b6f0167c527c4a08 | none (off-chain) |
| 19.5% APR, bypass (on-chain revert) | blocked | AprAboveMandate | tx_d9c3455e4a614243 | 0x0c18672cfdaba66a0debbb1ea88d03368a07859d7409e0dc61ba7b85bd000d01 |
| 600,000 above limit, bypass (revert) | blocked | AmountAboveLimit | tx_b24c1c7bc12d45b9 | 0x72eabb69e4f18cd83699a249df0ef160de1d9218a8d26c5d3ddbbd42beb1c431 |
| forced draw on injected invoice, no TX-2 | blocked | NotApproved | tx_ae8de9401dc241bf | none (off-chain) |
| re-saved PDF registered again (A2) | blocked | DuplicateReceivable | tx_6c8aecaef40148d0 | 0x45b32399161c281cdf367cffcc24b22e61bf17c7de1a4ba6fc61feb1b4e64e26 |
| pause | executed |  | tx_5149695a91fc41d3 | 0x1ad9967cc67121aeb3ee5e84346028e45d1f8514da3f55c40cea9e44501e9d9a |
| draw while paused | blocked | Paused | tx_d4042cdc80db4828 | none (off-chain) |
| unpause (owner) | executed |  | tx_b5e3af23baa54eee | 0xa1e6e76398ff313bb267bff004dfafbe8eb357afd63e82c534167637c2fb12b5 |
