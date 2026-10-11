# Demo transactions (fisco ledger)

Run on 2026-10-11, run id 20261011122302. Every hash below is a fisco transaction hash. Receipts go to FISCO_RECEIPTS_DIR.

| step | status | block reason | tx_id | chain_ref |
|---|---|---|---|---|
| register inv_happy | executed |  | tx_04d0558cdfd847a7 | 0xca427c5b215db42d8772ca24d5619809a01dfc69fe382b2e8ce9199e2faecd6d |
| approve (TX-2) inv_happy | executed |  | tx_8cf6af6759144806 | 0x6be10faf53f3027d362f5b6f10f2703dac9ac4cd6be1bb9334e83b4bde0083a1 |
| execute draw (TX-4) inv_happy | executed |  | tx_a67ae643afd449ad | 0x43023ce5e7fdb29f0429e5fa88126adf08d0c4e03199e5b8e28fee8afeec7989 |
| settle, buyer paid 749000.00 (TX-5) | executed |  | tx_99dd5859f3a24974 | 0x2783cd60cb55de4005c26c07257b227b2e019d3a781930947e89ac4ac96a69b0 |
| execute 980,000 (above 837,500) | pending_approval |  | tx_8c11708450884f8c | 0x267887986a61aff4a3b67ce09510a3e7abac7ff00916c64423fe71f739d32fac |
| approver confirms | executed |  | tx_326e599fa0914d97 | 0x38e399bc4ef26de2e45bc985764b307735c0acfb7685908c58d5cbb1c550f82a |
| draw at 19.5% APR (L3) | blocked | AprAboveMandate | tx_5702642ddf5844e2 | none (off-chain) |
| draw 600,000 above limit (L3) | blocked | AmountAboveLimit | tx_d43c8629b54a4e5b | none (off-chain) |
| 19.5% APR, bypass (on-chain revert) | blocked | AprAboveMandate | tx_38daf4b3038c49fd | 0x4f2d22e929adc19e77185e8e5fe8ea87abba6598638b9c6f90d0b29555bcc3b8 |
| 600,000 above limit, bypass (revert) | blocked | AmountAboveLimit | tx_8b59ab5b7d0c4778 | 0xed2cea84e4925891d7bd21a1d157c65cdde1101ba42c20acdb1e8f5e9ade388a |
| forced draw on injected invoice, no TX-2 | blocked | NotApproved | tx_8a4a4c34c6734ab9 | none (off-chain) |
| re-saved PDF registered again (A2) | blocked | DuplicateReceivable | tx_119714b694354007 | 0x30a3df21e618d5eab6b032b171736e0fe7e81f0fd36f08392b3ac6c212ff15b8 |
| pause | executed |  | tx_66c9b9d093034096 | 0x8e68418b9f6461c07e671b218e763c6a56782fa9e8cbdac6d87911d5132d73ad |
| draw while paused | blocked | Paused | tx_7aad686a51af4ea5 | none (off-chain) |
| unpause (owner) | executed |  | tx_741ba4c6c0e24d67 | 0x2a01e876af47f4db61616f7cfa69082d113730bc4dc7c7c727e70c15bbd32cad |
