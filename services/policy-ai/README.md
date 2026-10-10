# policy-ai

Owner: Policy AI engineer. Scope: financing policy, credit risk model.

Endpoint: `POST /policy/decide` on port 8002, plus `GET /health`. Request and response models are in [`shared/schemas.py`](../../shared/schemas.py).

Design doc: [`docs/04-policy-ai.md`](../../docs/04-policy-ai.md). Assistant instructions for this service: `CLAUDE.md` in this folder (added by the service owner).

Status: stub. The endpoint returns a fixed response that matches the contract so the end-to-end demo runs.

## Run

From the repo root, with `.env` in place:

```bash
pip install -r services/policy-ai/requirements.txt
python -m uvicorn app.main:app --app-dir services/policy-ai --port 8002 --reload
```

## Test

```bash
pytest services/policy-ai
ruff check services/policy-ai
```
