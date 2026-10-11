"""Deploy and wire the five wallet contracts on the FISCO BCOS Air chain, then write the FISCO block of
contracts/deployments.json (addresses only, no keys).

Runs where the FISCO SDK and the chain's SDK certificates are available: the fisco-air container (see the
README). Same steps as scripts/deploy.py (Anvil), with the mandate and payees from config/.

    python services/agent-wallet/scripts/deploy_fisco.py \
        --sdk-dir /opt/python-sdk --config-dir /work/sdk --accounts-dir /work/accounts
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]

from ledger.fisco import (  # noqa: E402
    address_of,
    encode_call,
    encode_constructor,
    load_artifact,
    open_clients,
    revert_reason,
    selector,
)

from app.models import load_mandate, load_payees  # noqa: E402
from shared.money import to_units  # noqa: E402

CONFIG = SERVICE / "config"
DEPLOYMENTS = SERVICE / "contracts" / "deployments.json"
RECEIPTS = SERVICE / "eval" / "fisco-receipts"  # every deploy transaction's receipt, as JSON (evidence)
ROLES = ["deployer", "agent", "approver", "risk_oracle", "buyer"]
LIQUIDITY = 500000000  # 5,000,000.00 tTHB, the same as bootstrap_demo in the mock
MAX_UINT = 2**256 - 1
BPS = 10_000


def as_int(value) -> int:
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)


def check(receipt: dict, label: str) -> dict:
    if as_int(receipt.get("status", 0)) != 0:
        raise SystemExit(f"{label} reverted: {revert_reason(receipt.get('output')) or receipt.get('status')}")
    print(f"  {label:34s} {receipt['transactionHash']}  block {as_int(receipt['blockNumber'])}")
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    path = RECEIPTS / f"{receipt['transactionHash']}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def deploy(client, name: str, args: list) -> str:
    artifact = load_artifact(name)
    code = artifact["bytecode"]["object"]
    code = code if code.startswith("0x") else "0x" + code
    ctor = encode_constructor(artifact["abi"], args)
    receipt = client.deploy(code + ctor)
    check(receipt, f"deploy {name}")
    return receipt["contractAddress"]


def send(client, to: str, abi: list, fn: str, args: list) -> dict:
    receipt = client.sendRawTransaction(to, None, None, None, function_bin_data=encode_call(abi, fn, args))
    return check(receipt, fn)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk-dir", default="/work/python-sdk")
    parser.add_argument("--config-dir", default="/work/sdk")
    parser.add_argument("--accounts-dir", default="/work/accounts")
    args = parser.parse_args()

    # Each deployment is a new set of contracts, so its receipts replace the last set's.
    for old in RECEIPTS.glob("*.json") if RECEIPTS.exists() else []:
        old.unlink()

    accounts = Path(args.accounts_dir)
    clients = open_clients(
        {role: str(accounts / f"{role}.pem") for role in ROLES}, args.sdk_dir, args.config_dir
    )
    addresses = {role: address_of(client) for role, client in clients.items()}
    owner = clients["deployer"]
    mandate = load_mandate(CONFIG / "mandate.demo.json")
    payees = load_payees(CONFIG / "payees.json")
    abi = {
        name: load_artifact(name)["abi"]
        for name in ("MockStable", "PolicyGuard", "ReceivableRegistry", "FinancingVault", "AgentWallet")
    }

    print("deploying")
    token = deploy(owner, "MockStable", [])
    guard = deploy(owner, "PolicyGuard", [1000])  # FISCO block.timestamp is in milliseconds
    registry = deploy(owner, "ReceivableRegistry", [addresses["risk_oracle"]])
    vault = deploy(owner, "FinancingVault", [token, payees["PLATFORM:fee"].address])
    wallet = deploy(owner, "AgentWallet", [addresses["agent"], addresses["approver"], guard])

    print("wiring")
    send(owner, guard, abi["PolicyGuard"], "wire", [wallet])
    send(owner, registry, abi["ReceivableRegistry"], "wire", [wallet, vault, guard])
    send(owner, vault, abi["FinancingVault"], "wire", [wallet, registry, guard])
    send(owner, vault, abi["FinancingVault"], "setSettlementPayer", [addresses["buyer"]])

    expires = int(mandate.expires_at.timestamp()) if mandate.expires_at else 0
    send(
        owner,
        guard,
        abi["PolicyGuard"],
        "setMandate",
        [
            to_units(mandate.max_amount_per_tx, 2),
            to_units(mandate.daily_cap, 2),
            int(mandate.max_ltv * BPS),
            int(mandate.max_apr * BPS),
            to_units(mandate.human_review_above, 2),
            expires,
            mandate.mandate_hash,
        ],
    )
    for signature, target in [
        ("register(bytes32,bytes32,address,uint256,uint64)", registry),
        ("draw(bytes32,uint256,uint16,address,uint256,uint256)", vault),
        ("repay(bytes32,uint256)", vault),
    ]:
        send(owner, guard, abi["PolicyGuard"], "setCall", [target, "0x" + selector(signature).hex(), True])
    for party in ["SELLER:siam-fresh-pack", "LENDER:lender_a", "LENDER:lender_b", "PLATFORM:fee"]:
        if payees[party].kyc_verified:  # only KYC-verified payees are allowlisted on chain
            send(owner, guard, abi["PolicyGuard"], "setPayee", [payees[party].address, True])

    print("liquidity (TX-3 stand-in) and the buyer's approval")
    send(owner, token, abi["MockStable"], "mint", [addresses["deployer"], LIQUIDITY])
    send(owner, token, abi["MockStable"], "approve", [vault, MAX_UINT])
    send(owner, vault, abi["FinancingVault"], "deposit", [LIQUIDITY])
    send(owner, token, abi["MockStable"], "mint", [addresses["buyer"], LIQUIDITY])
    send(clients["buyer"], token, abi["MockStable"], "approve", [vault, MAX_UINT])

    record = {
        "chain_id": "chain0",
        "group": "group0",
        "rpc": "https://127.0.0.1:20200 (and 20201-20203)",
        "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "roles": addresses,
        "contracts": {
            "MockStable": token,
            "PolicyGuard": guard,
            "ReceivableRegistry": registry,
            "FinancingVault": vault,
            "AgentWallet": wallet,
        },
        "mandate_hash": mandate.mandate_hash,
    }
    everything = json.loads(DEPLOYMENTS.read_text(encoding="utf-8")) if DEPLOYMENTS.exists() else {}
    everything["fisco"] = record
    DEPLOYMENTS.write_text(json.dumps(everything, indent=2) + "\n", encoding="utf-8")
    print(f"wrote the fisco block of {DEPLOYMENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
