# OCR and Fraud Evidence

This context describes invoice and purchase-order observations and explainable document risk signals. It does not establish delivery, legal validity, credit approval, or authority to transfer funds.

## Language

**Invoice**:
A document asserting that a supplier requests payment from a buyer for specified goods or services. Its presence does not prove that the asserted transaction occurred.

**Purchase Order (PO)**:
A document asserting a buyer's order from a supplier, with stated commercial terms. A matching PO corroborates an invoice without proving delivery or acceptance.

**Observation**:
Content read from a particular document location before interpretation or normalization.

**Field Evidence**:
The observations supporting a particular extracted value, including their source locations and any uncertainty.

**Comparison Check**:
An assessment of one invoice-to-PO relationship as match, mismatch, or unknown, supported by evidence from each document.

**Exact Duplicate**:
A repeat of the same document bytes. This says nothing about the document's authenticity.

**Semantic Duplicate**:
A repeated invoice identity under declared normalization rules, potentially represented by different document bytes.

**Legal Entity Identity**:
A jurisdiction-aware, typed legal identifier supported by document evidence. A similar company name alone does not establish the same legal entity.

**Shared Account Signal**:
Evidence that distinct identified entities reference the same scoped bank-account identifier. The relationship requires contextual review and does not establish collusion.

**Suspicious Cluster Signal**:
A connected group supported by multiple independent document risk signals. It is an investigative finding, not proof of fraud.

**Review**:
A result requiring human assessment because evidence is missing, ambiguous, conflicting, unsupported, or carries risk signals.
_Avoid_: Approval, fraud verdict

**Observed Invoice History**:
Previously processed invoice evidence available to this OCR context. It is distinct from a ledger of financed invoices or accepted PO allocations.
