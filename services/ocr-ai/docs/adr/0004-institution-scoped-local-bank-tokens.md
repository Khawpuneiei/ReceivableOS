# Institution scope for local bank observations

Status: implemented inside OCR ownership during the user-authorized reliability workstreams.

Local account digits are not globally unique across institutions. Previously the available country/scheme scope could link equal digits at different banks. Local account observations now require printed, sufficiently confident `Bank Institution` evidence as well as account, country and scheme. Missing institution produces `BANK_INSTITUTION_UNKNOWN` and no graph account token. Conflicting or low-confidence bank evidence also cannot merge account nodes.

New tokens use `bank:v2` and a separate `bank-account-v2` HMAC namespace. LOCAL includes scheme, country, institution and account; IBAN keeps country/scheme/full printed account scope without requiring a separate institution field. This does not validate an IBAN checksum or establish ownership/authenticity of printed banking information. Institution aliases are not heuristically merged.

Historical `bank:v1` payloads remain readable but never equal v2 tokens. There is no silent backfill or history reset. Cross-version shared-account coverage is therefore incomplete, while file/semantic duplicate detection remains separate. Production migration needs authoritative identity evidence and an operator-reviewed route; raw accounts are intentionally unavailable in stored observations.

Synthetic legacy fixtures now print an explicit fictional institution identifier. Global stress fixtures omit banking fields. The original four-scan/HTTP artifacts predate this fixture revision and remain historical observations, not measurements of the new corpus.
