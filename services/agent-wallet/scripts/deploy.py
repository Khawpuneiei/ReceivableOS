"""Deploy and wire the five wallet contracts, then write contracts/deployments.json (addresses only).

Local EVM only: Anvil on chain id 31337, unlocked accounts. FISCO BCOS is not implemented yet.

    anvil --port 8545
    python services/agent-wallet/scripts/deploy.py --deployer 0x... --agent 0x... --approver 0x... \
        --risk-oracle 0x... --buyer 0x...

The wiring follows contracts/README.md. The mandate and payees come from config/, so the on-chain numbers
match the Python mock. The deployer also provides the lender liquidity (TX-3 stand-in).
"""

import argparse
import json
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1]), str(SERVICE / "scripts")]

from evm import Chain, selector  # noqa: E402

from app.models import load_mandate, load_payees  # noqa: E402
from shared.money import to_units  # noqa: E402

CONFIG = SERVICE / "config"
DEPLOYMENTS = SERVICE / "contracts" / "deployments.json"
MAX_UINT = str(2**256 - 1)
LIQUIDITY = 500000000  # 5,000,000.00 tTHB, the same as bootstrap_demo in the mock

REGISTER_SIG = "register(bytes32,bytes32,address,uint256,uint64)"
DRAW_SIG = "draw(bytes32,uint256,uint16,address,uint256,uint256)"
REPAY_SIG = "repay(bytes32,uint256)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc", default="http://127.0.0.1:8545")
    parser.add_argument(
        "--deployer", required=True, help="owner of every contract; also the lender liquidity"
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--risk-oracle", required=True)
    parser.add_argument("--buyer", required=True, help="the account that pays the invoice at settlement")
    args = parser.parse_args()

    chain = Chain(args.rpc)
    mandate = load_mandate(CONFIG / "mandate.demo.json")
    payees = load_payees(CONFIG / "payees.json")
    owner = args.deployer

    token = chain.deploy("src/MockStable.sol:MockStable", owner)
    guard = chain.deploy("src/PolicyGuard.sol:PolicyGuard", owner)
    registry = chain.deploy("src/ReceivableRegistry.sol:ReceivableRegistry", owner, [args.risk_oracle])
    vault = chain.deploy(
        "src/FinancingVault.sol:FinancingVault", owner, [token, payees["PLATFORM:fee"].address]
    )
    wallet = chain.deploy("src/AgentWallet.sol:AgentWallet", owner, [args.agent, args.approver, guard])
    print(f"deployed: token {token} guard {guard} registry {registry} vault {vault} wallet {wallet}")

    chain.send(guard, "wire(address)", [wallet], owner)
    chain.send(registry, "wire(address,address,address)", [wallet, vault, guard], owner)
    chain.send(vault, "wire(address,address,address)", [wallet, registry, guard], owner)
    chain.send(vault, "setSettlementPayer(address)", [args.buyer], owner)

    expiry = int(mandate.expires_at.timestamp()) if mandate.expires_at else 0
    chain.send(
        guard,
        "setMandate(uint256,uint256,uint16,uint16,uint256,uint64,bytes32)",
        [
            to_units(mandate.max_amount_per_tx),
            to_units(mandate.daily_cap),
            int(mandate.max_ltv * 10000),
            int(mandate.max_apr * 10000),
            to_units(mandate.human_review_above),
            expiry,
            mandate.mandate_hash,
        ],
        owner,
    )
    for target, sig in [(registry, REGISTER_SIG), (vault, DRAW_SIG), (vault, REPAY_SIG)]:
        chain.send(guard, "setCall(address,bytes4,bool)", [target, selector(sig), "true"], owner)
    for party in ["SELLER:siam-fresh-pack", "LENDER:lender_a", "LENDER:lender_b", "PLATFORM:fee"]:
        chain.send(guard, "setPayee(address,bool)", [payees[party].address, "true"], owner)

    # TX-3 stand-in: the deployer deposits liquidity. The buyer approves the vault for settlement.
    chain.send(token, "mint(address,uint256)", [owner, LIQUIDITY], owner)
    chain.send(token, "approve(address,uint256)", [vault, MAX_UINT], owner)
    chain.send(vault, "deposit(uint256)", [LIQUIDITY], owner)
    chain.send(token, "mint(address,uint256)", [args.buyer, LIQUIDITY], owner)
    chain.send(token, "approve(address,uint256)", [vault, MAX_UINT], args.buyer)

    record = {
        "chain_id": 31337,
        "rpc": args.rpc,
        "roles": {
            "owner": owner,
            "agent": args.agent,
            "approver": args.approver,
            "risk_oracle": args.risk_oracle,
            "buyer": args.buyer,
        },
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
    everything["anvil"] = record
    DEPLOYMENTS.write_text(json.dumps(everything, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {DEPLOYMENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
