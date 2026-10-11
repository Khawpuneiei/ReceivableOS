# Demo transactions (fisco ledger)

Run on 2026-10-11. Every hash below is a fisco transaction hash. The receipts are in eval/fisco-receipts-demo/.

| step | status | block reason | tx_id | chain_ref |
|---|---|---|---|---|
| register inv_happy | executed |  | tx_9fa8c9992a084877 | 0x522b3d20f8f162d4bdc2248dba78e1222287efa585b1ab9ef952ac995bd52d78 |
| approve (TX-2) inv_happy | executed |  | tx_c8fd5d9c698d4d8a | 0x80e52bf1be019dbb1ec0006941432574707cb43dfd5ea1a6242f06bf59c53d3c |
| execute draw (TX-4) inv_happy | executed |  | tx_6d44027185034276 | 0x83270d1f3b77382fdac5922743cb77e8fbfa2f58ef54c9afba2485623044474a |
| settle, buyer paid 749,000 (TX-5) | executed |  | tx_50b8348dbce142c0 | 0x831035b01761696a75b2c2edccbf0203332d6361c6b4d038a57566a98f0addf8 |
| execute 980,000 (above 837,500) | pending_approval |  | tx_6a0b221fecec4401 | 0x06fb18c00ccfc42f0fa69429515a12eaded09feb932a79f241fe40979531b439 |
| approver confirms | executed |  | tx_52e3c5c4cb624110 | 0xc3fa274fc7a4baf370bfe74cc9c4be8966158fded2faf977f909131259048005 |
| draw at 19.5% APR (L3) | blocked | AprAboveMandate | tx_8ffbb041679446f0 | none (off-chain) |
| draw 600,000 above limit (L3) | blocked | AmountAboveLimit | tx_baa51ba2fb954c25 | none (off-chain) |
| 19.5% APR, bypass (on-chain revert) | blocked | AprAboveMandate | tx_869cd6fe448d4652 | 0x201a7f3e3d687653f123283f3995a1387874b01a9240d24e715cbcfb96e0fa86 |
| 600,000 above limit, bypass (revert) | blocked | AmountAboveLimit | tx_e0104de2bb3548bf | 0x063009b66cccee41f81aaec7cc87c6f6b0fb4b280d83ec342672884c5da9f62e |
| forced draw on injected invoice, no TX-2 | blocked | NotApproved | tx_ad1483de69534f51 | none (off-chain) |
| re-saved PDF registered again (A2) | blocked | DuplicateReceivable | tx_4e2f667fbde548d7 | 0xeb650104f6b343352bbb1d68c4ca188ac3ccbb2f226b9984bd732cc7ef41f1a1 |
| pause | executed |  | tx_6e4c233f26224d77 | 0xab2dccec6afc5a57119a744cd8080cf7f383b0b7d2d6a3e8cf8efc0e4c3e7dc9 |
| draw while paused | blocked | Paused | tx_3e8ed92c5ab64bae | none (off-chain) |
| unpause (owner) | executed |  | tx_977935611c0a4e97 | 0x0f79bb6661a5b17fc5de0e8a2a3fe996e18bf7829c16a8ccfdfe5c4011bd74f3 |
