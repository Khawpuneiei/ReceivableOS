"""On-chain smoke test on Anvil: the money loop, checked against the Python mock's numbers (CLAUDE.md §11).

Run scripts/deploy.py first. The loop's transactions change state. The refusals are read-only cast calls.
Exit code 1 if any check fails, so this can gate a CI job later.

    python services/agent-wallet/scripts/evm_smoke.py
"""

import json
import sys
from pathlib import Path

from Crypto.Hash import keccak

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1]), str(SERVICE / "scripts")]

from evm import Chain, calldata  # noqa: E402

from app.models import load_payees  # noqa: E402

CONFIG = SERVICE / "config"
DEPLOYMENTS = SERVICE / "contracts" / "deployments.json"

REGISTER_SIG = "register(bytes32,bytes32,address,uint256,uint64)"
DRAW_SIG = "draw(bytes32,uint256,uint16,address,uint256,uint256)"
REPAY_SIG = "repay(bytes32,uint256)"
EXECUTE_SIG = "execute(address,bytes,uint256,uint16,bytes32,bytes32)"
APPROVE_SIG = "approve(bytes32,uint256,uint16,bytes32)"
BALANCE_SIG = "balanceOf(address)(uint256)"
FEES_SIG = "lenderFees(address)(uint256)"


def h32(text: str) -> str:
    return "0x" + keccak.new(digest_bits=256, data=text.encode()).hexdigest()


def main() -> int:
    deployment = json.loads(DEPLOYMENTS.read_text(encoding="utf-8"))["anvil"]
    chain = Chain(deployment["rpc"])
    c, roles = deployment["contracts"], deployment["roles"]
    payees = load_payees(CONFIG / "payees.json")
    seller = payees["SELLER:siam-fresh-pack"].address
    lender = payees["LENDER:lender_a"].address
    platform = payees["PLATFORM:fee"].address

    fp, doc, dh = h32("fp:smoke"), h32("doc:smoke"), h32("decision:smoke")
    results: list[tuple[str, object, object]] = []

    def execute(target: str, data: str, amount: int, apr: int, sender: str) -> None:
        chain.send(c["AgentWallet"], EXECUTE_SIG, [target, data, amount, apr, fp, dh], sender)

    def refused(target: str, data: str, amount: int, apr: int, reason: str) -> None:
        code, out = chain.call(
            c["AgentWallet"], EXECUTE_SIG, [target, data, amount, apr, fp, dh], roles["agent"]
        )
        results.append((f"refused: {reason}", reason in out, reason))

    def expect(name: str, actual: int, want: int) -> None:
        results.append((name, actual, want))

    # 1. register (TX-1) and approve (TX-2)
    execute(
        c["ReceivableRegistry"],
        calldata(REGISTER_SIG, [fp, doc, seller, 74900000, 1794000000]),
        0,
        0,
        roles["agent"],
    )
    chain.send(c["ReceivableRegistry"], APPROVE_SIG, [fp, 52430000, 1095, dh], roles["risk_oracle"])

    # 2. the mandate refuses 19.5% APR, even though the oracle approved 10.95%
    refused(
        c["FinancingVault"],
        calldata(DRAW_SIG, [fp, 52430000, 1950, lender, 534786, 224700]),
        52430000,
        1950,
        "AprAboveMandate",
    )

    # 3. the draw (TX-4) and the mock's numbers
    execute(
        c["FinancingVault"],
        calldata(DRAW_SIG, [fp, 52430000, 1095, lender, 534786, 224700]),
        52430000,
        1095,
        roles["agent"],
    )
    expect(
        "seller nets 516,705.14 after draw", chain.read_uint(c["MockStable"], BALANCE_SIG, [seller]), 51670514
    )
    expect("platform fee 2,247.00", chain.read_uint(c["MockStable"], BALANCE_SIG, [platform]), 224700)
    expect(
        "lender discount fee 5,347.86 booked",
        chain.read_uint(c["FinancingVault"], FEES_SIG, [lender]),
        534786,
    )

    # 4. a second draw on the same invoice is refused
    refused(
        c["FinancingVault"],
        calldata(DRAW_SIG, [fp, 1000000, 1095, lender, 0, 0]),
        1000000,
        1095,
        "AlreadyDrawn",
    )

    # 5. settlement (TX-5): lender principal first, then the seller reserve
    execute(c["FinancingVault"], calldata(REPAY_SIG, [fp, 74900000]), 0, 0, roles["agent"])
    expect(
        "lender principal 524,300.00 back", chain.read_uint(c["MockStable"], BALANCE_SIG, [lender]), 52430000
    )
    expect(
        "seller after settlement (516,705.14 + 224,700.00)",
        chain.read_uint(c["MockStable"], BALANCE_SIG, [seller]),
        51670514 + 22470000,
    )

    failed = 0
    print(f"{'check':58s} {'on-chain':>14s} {'mock':>14s}  result")
    for name, actual, want in results:
        ok = actual == want if not isinstance(want, str) else bool(actual)
        failed += 0 if ok else 1
        shown_actual = actual if not isinstance(actual, bool) else ("refused" if actual else "NOT refused")
        shown_want = want if not isinstance(want, str) else f"revert {want}"
        print(f"{name:58s} {str(shown_actual):>14s} {str(shown_want):>14s}  {'PASS' if ok else 'FAIL'}")
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
