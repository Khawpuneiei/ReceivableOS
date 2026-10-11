"""eval/fisco-deployment.md is written from the saved receipts: one row per transaction, in block order."""

import importlib.util
import json
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
DEPLOYED = "0x" + "ab" * 20
CALLED = "0x" + "cd" * 20


def load_deploy_script():
    spec = importlib.util.spec_from_file_location("deploy_fisco", SERVICE / "scripts" / "deploy_fisco.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt(tx: str, block: int, to: str, contract: str = "", status: int = 0) -> dict:
    return {
        "transactionHash": tx,
        "blockNumber": block,
        "to": to,
        "contractAddress": contract,
        "status": status,
    }


def test_the_record_lists_each_saved_receipt_in_block_order(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    saved = [
        receipt("0x02", 12, to=CALLED),
        receipt("0x01", 11, to="", contract=DEPLOYED),
        receipt("0x03", 13, to=CALLED, status=16),  # a reverted call
    ]
    for r in saved:
        (receipts / f"{r['transactionHash']}.json").write_text(json.dumps(r), encoding="utf-8")
    record = {
        "chain_id": "chain0",
        "group": "group0",
        "deployed_at": "2026-10-11T12:00:00+00:00",
        "contracts": {"MockStable": DEPLOYED},
    }
    out = tmp_path / "fisco-deployment.md"

    load_deploy_script().write_deployment_record(record, receipts=receipts, out=out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert "Deployed 2026-10-11T12:00:00+00:00." in lines[2]
    assert f"- MockStable: `{DEPLOYED}`" in lines
    rows = [line for line in lines if line.startswith("| ") and line[2].isdigit()]
    assert rows == [
        f"| 11 | `0x01` | deploy | {DEPLOYED} | ok |",
        "| 12 | `0x02` | call | - | ok |",
        "| 13 | `0x03` | call | - | reverted |",
    ]
