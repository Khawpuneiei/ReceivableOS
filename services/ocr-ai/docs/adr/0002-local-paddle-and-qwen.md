---
status: accepted
---

# Use local PaddleOCR with a concurrent Qwen-VL experiment

The user explicitly selected PaddleOCR and Qwen-VL together in this iteration. Prefer PDF embedded text/layout, use staged regular PaddleOCR v5 mobile detector plus Thai recognizer for scans, and run Qwen3-VL 4B Instruct through loopback Ollama as a candidate reader. A proposed value cannot replace missing or disagreeing grounded OCR evidence. Unavailable/invalid candidates, disagreements, and limited page coverage require review. Both engines are measured against labeled English/Thai synthetic scans without claiming universal language support.

On this M5/macOS arm64 environment, Paddle runs on CPU. The `qwen3-vl:4b` tag resolved to a Thinking model that exhausted the generation bound before producing JSON, so the experiment switched to explicit `qwen3-vl:4b-instruct`. Pin/review model versions and digests when upgrading. This choice adds local installation and inference latency, but avoids a cloud provider and preserves document-processing boundaries.

References: [Paddle OCR pipeline](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html), [Paddle macOS installation](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/macos-pip_en.html), [Ollama Qwen tags](https://ollama.com/library/qwen3-vl/tags), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [chat API](https://docs.ollama.com/api/chat). Published model coverage is not our accuracy evidence; see the measured report.
