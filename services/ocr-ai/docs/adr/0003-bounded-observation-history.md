---
status: accepted
---

# Persist bounded OCR observations separately from financial decisions

The user authorized the recommended Q3 plan: OCR-owned SQLite persists minimal matching fields, scoped HMAC entity/bank tokens, hashes, anomaly codes and evidence locations. No raw accounts, source uploads, full extracted text, or financial acceptance state is stored. A 500-observation bound fails safely at capacity; observations are not silently evicted. Idempotency keys bind request bytes and prevent retry-generated duplicate observations. Reset requires explicit development mode and permission and is not exposed over HTTP.

Byte identity and scoped semantic identity remain distinct. Names alone never merge graph companies. Shared bank tokens produce contextual review; suspicious clusters require multiple independent document anomalies across scoped issuers. The resulting score is a deterministic signal, not calibrated fraud probability or prior-financing evidence. Persistent observations improve restart behavior but require future key rotation, tenant isolation, retention, and trusted financial-ledger decisions before production integration.
