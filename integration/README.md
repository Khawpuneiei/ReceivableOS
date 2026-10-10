# integration

Owner: PM. End-to-end demo of the full ReceivableOS flow.

- `run_demo.py` calls `POST /ocr/extract`, then `POST /policy/decide`, then `POST /wallet/execute`, and prints each response.
- `samples/` holds demo invoices and supplier/buyer profiles. Add the attack cases here too (duplicate invoice, injected text, over-limit amount, untrusted payee) so the demo can show each one being blocked.

```bash
python integration/run_demo.py                       # default sample
python integration/run_demo.py path/to/invoice.pdf   # your own file
```

Service URLs come from `OCR_URL`, `POLICY_URL`, `WALLET_URL` (defaults: ports 8001, 8002, 8003 on localhost).
