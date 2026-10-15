# One image for the whole ReceivableOS stack; docker-compose.yml picks the service by command. Owner: PM.
# Mock ledger and offline OCR only: no FISCO node, no Paddle/Qwen models, no LLM key needed.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY services/ocr-ai/requirements.txt services/ocr-ai/requirements.txt
COPY services/policy-ai/requirements.txt services/policy-ai/requirements.txt
COPY services/agent-wallet/requirements.txt services/agent-wallet/requirements.txt
COPY services/orchestrator/requirements.txt services/orchestrator/requirements.txt
COPY ui/requirements.txt ui/requirements.txt
RUN pip install \
    -r services/ocr-ai/requirements.txt \
    -r services/policy-ai/requirements.txt \
    -r services/agent-wallet/requirements.txt \
    -r services/orchestrator/requirements.txt \
    -r ui/requirements.txt

COPY shared shared
COPY data data
COPY services services
COPY ui ui

RUN useradd --create-home --uid 10001 app && mkdir -p /state && chown -R app /app /state
USER app

# Overridden per service in docker-compose.yml.
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "services/orchestrator", "--host", "0.0.0.0", "--port", "8000"]
