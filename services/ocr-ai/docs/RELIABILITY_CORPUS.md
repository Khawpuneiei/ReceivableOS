# English-primary reliability corpus

The user authorized all six reliability workstreams on 10 October 2026 and asked for English to be primary, Chinese to be considered, and Thai to remain covered.

## Implemented evaluation design

| Track | Documents | Invoice / PO | Digital PDF / PNG |
|---|---:|---:|---:|
| English, primary | 48 | 24 / 24 | 32 / 16 |
| Simplified Chinese, experimental | 16 | 8 / 8 | 8 / 8 |
| Thai, secondary | 16 | 8 / 8 | 8 / 8 |
| Total | 80 | 40 / 40 | 48 / 32 |

Four layouts exercise stacked fields, separated label/value spans, two panels sharing row coordinates, and commercial line tables on a separate PDF page. The last layout is a frozen synthetic holdout: 20 documents; development contains 60. Invoice/PO pairs and variants remain in their source family; no family crosses the split. The commercial PNG contains only the header page and is explicitly annotated as having no line table.

English cases also exercise USD, EUR, CNY, JPY, KWD and GBP, two line items, missing due dates, ambiguous monetary separators, explicit AI instructions and ordinary payment notices. Chinese and Thai include native-script company names, native labels and benign notes. These are printed examples, not evidence that every currency, language, tax regime or legal identifier is supported.

The [generator](../datagen/reliability.py) writes OCR-owned `data/invoices/reliability/` and `manifest.jsonl`. Each manifest record identifies its family, split, input SHA-256, truth, expected line content, and approximate field regions. Amount comparison uses normalized Decimal equality; other evaluated scalar fields use exact source strings. A missing field correctly represented as null can match its annotation; an all-fields annotation match does not mean the document is complete or safe to accept.

## Models and reporting

All 80 documents are evaluated through real PDF parsing or staged Paddle recognition. The recognition profile is selected by trusted experiment metadata, not a user filename or document instruction. English uses `en_PP-OCRv5_mobile_rec`, Chinese uses `PP-OCRv5_mobile_rec`, and Thai uses `th_PP-OCRv5_mobile_rec`, with the same v5 mobile detector. This is an explicit language-profile experiment, not automatic multilingual model routing.

Qwen is evaluated on 24 scans: both document types in each language/layout, with three repeats for the six stacked cases (36 calls total). Results report candidate accuracy, wrong present fields, unresolved/review outcomes, benign injection alerts and observed latency separately. The grounding prototype remains outside the live pipeline.

## Independent-source research and remaining limitation

The [DocILE organizers](https://docile.rossum.ai/) provide business-document field/line localization tasks and require a dataset access request for research use. It is a candidate for independent layout evaluation, not an already available OCR fixture source. Its permissions, data suitability and target-language coverage must be checked before adoption; no access request, acceptance of terms or dataset download was made here.

The current 80 documents and annotations are generated together. Family separation prevents obvious split leakage but cannot make them independently sourced or human-annotated. External document validation and deployment traffic/latency targets remain unresolved. Do not call this corpus a global real-world benchmark.

## Primary model references

- [PaddleOCR multilingual v5 model documentation](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html) distinguishes model language profiles; published model capabilities are not measured extraction accuracy.
- [Qwen3-VL-4B-Instruct model card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct) describes OCR capabilities; our Ollama quantization, schema, resolution and prompt still require local evaluation.
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) documents response-shape constraints. Local results show that valid JSON alone does not establish field truth or injection detection quality.
