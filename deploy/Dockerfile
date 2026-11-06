# One image for the whole ReceivableOS stack; docker-compose.yml picks the service by command. Owner: PM.
# Mock ledger and offline OCR only: no FISCO node, no Paddle/Qwen models, no LLM key needed.
# Two stages: "builder" installs every service's dependencies into a virtual environment, "runtime" copies only
# that environment and the code, so pip's build-time state never reaches the final image.

# ---- builder: dependencies only -------------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

# Requirements first, so the install layer stays cached until a requirements file changes.
COPY services/ocr-ai/requirements.txt services/ocr-ai/requirements.txt
COPY services/policy-ai/requirements.txt services/policy-ai/requirements.txt
COPY services/agent-wallet/requirements.txt services/agent-wallet/requirements.txt
COPY services/orchestrator/requirements.txt services/orchestrator/requirements.txt
COPY ui/requirements.txt ui/requirements.txt
# --without-pip: the base image's pip installs into the venv, so the venv does not carry a second copy of pip.
RUN python -m venv --without-pip /opt/venv \
    && pip --python /opt/venv/bin/python install \
    -r services/ocr-ai/requirements.txt \
    -r services/policy-ai/requirements.txt \
    -r services/agent-wallet/requirements.txt \
    -r services/orchestrator/requirements.txt \
    -r ui/requirements.txt

# ---- runtime: same base, the venv and the code, non-root -------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# The venv must sit at the same path as in the builder: its scripts (uvicorn, streamlit) hard-code it.
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app

RUN useradd --create-home --uid 10001 app && mkdir -p /state && chown app /app /state

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:root shared shared
COPY --chown=app:root data data
COPY --chown=app:root services services
COPY --chown=app:root ui ui

USER app

# Overridden per service in docker-compose.yml.
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "services/orchestrator", "--host", "0.0.0.0", "--port", "8000"]
