"""Deterministic mocked transport benchmark; never calls a hosted provider."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from app.cache import JsonCache  # noqa: E402
from app.llm_client import read_hosted_candidates  # noqa: E402
from app.qwen import VisionCandidates  # noqa: E402


def measure():
    actual_client = httpx.Client
    calls = []

    def handler(request):
        calls.append(1)
        time.sleep(0.25)
        value = {k: False if k == "instructions_found" else None for k in VisionCandidates.model_fields}
        return httpx.Response(
            200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(value)}]}
        )

    with (
        patch.dict(
            os.environ,
            {
                "LLM_API_KEY": "fake-benchmark-key",
                "LLM_MODEL": "fake-model",
                "LLM_PROVIDER": "anthropic",
                "OCR_HOSTED_VISION_ENABLED": "1",
            },
        ),
        patch("app.llm_client._cache", JsonCache()),
        patch(
            "app.llm_client.httpx.Client",
            lambda **kw: actual_client(**kw, transport=httpx.MockTransport(handler)),
        ),
    ):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(read_hosted_candidates, [["first"], ["second"]]))
        elapsed = time.perf_counter() - started
        assert all(result[0] is not None for result in results) and len(calls) == 2
        return {
            "scenario": "two distinct document keys, two threads",
            "mock_network_seconds_per_call": 0.25,
            "wall_seconds": round(elapsed, 4),
            "transport_calls": len(calls),
            "live_provider_called": False,
        }


if __name__ == "__main__":
    print(json.dumps(measure()))
