"""FISCO BCOS 3.x adapter (CLAUDE.md 5.7). Owner: Agent AI engineer.

Talks to the chain through the FISCO BCOS 3.x Python SDK, which wraps the native C SDK. The SDK is not on
PyPI. Clone FISCO-BCOS/python-sdk, run its bcos3sdklib/download_c_libs.py, and set FISCO_SDK_DIR to the clone
(see the README). The SDK is imported only when this adapter is created, so mock mode never needs it.

Calldata is encoded here with eth_abi from the contracts' ABI (the forge artifacts in contracts/out). Each
role signs with its own key through its own SDK client. A reverted transaction is still a transaction:
it returns
ok=False with its hash and the decoded string revert, as the mock does. Revert strings and check order are the
Solidity ones, so the same names come back on both ledgers.
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from Crypto.Hash import keccak

from app.models import ApproveIntent, DrawIntent, Mandate, RegisterIntent, SettleIntent
from ledger.base import ChainResult
from shared.money import to_units

TOKEN_DECIMALS = 2
BPS = 10_000
ZERO32 = "0x" + "00" * 32
ZERO4 = "0x00000000"
ARTIFACTS = Path(__file__).resolve().parents[1] / "contracts" / "out"
ERROR_STRING_SELECTOR = "08c379a0"  # Error(string), what require() reverts with
APPROVAL_REQUIRED_TOPIC = (
    "0x" + keccak.new(digest_bits=256, data=b"ApprovalRequired(uint256,bytes32,uint256)").hexdigest()
)


def keccak_hex(text: str) -> str:
    return "0x" + keccak.new(digest_bits=256, data=text.encode()).hexdigest()


def selector(signature: str) -> bytes:
    return bytes.fromhex(keccak_hex(signature)[2:10])


def load_artifact(name: str) -> dict:
    """The forge artifact for a contract, e.g. name='FinancingVault'."""
    path = ARTIFACTS / f"{name}.sol" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _as_int(value: Any) -> int:
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    return int(value or 0)


def _bytes_of(value: str) -> bytes:
    return bytes.fromhex(value[2:] if value.startswith("0x") else value)


def encode_call(abi: list, fn: str, args: list) -> str:
    """Calldata for abi function `fn` with args, as 0x-prefixed hex."""
    from eth_abi import encode_abi
    from eth_utils import to_checksum_address

    item = next(i for i in abi if i.get("type") == "function" and i["name"] == fn)
    types = [i["type"] for i in item["inputs"]]
    values = []
    for value, typ in zip(args, types, strict=True):
        if typ == "address":
            values.append(to_checksum_address(value))
        elif typ.startswith("bytes"):
            values.append(_bytes_of(value) if isinstance(value, str) else bytes(value))
        elif typ == "bool":
            values.append(bool(value))
        else:
            values.append(int(value))
    return "0x" + (selector(f"{fn}({','.join(types)})") + encode_abi(types, values)).hex()


def encode_constructor(abi: list, args: list) -> str:
    from eth_abi import encode_abi
    from eth_utils import to_checksum_address

    item = next((i for i in abi if i.get("type") == "constructor"), None)
    if not item or not args:
        return ""
    types = [i["type"] for i in item["inputs"]]
    values = [to_checksum_address(a) if t == "address" else int(a) for a, t in zip(args, types, strict=True)]
    return encode_abi(types, values).hex()


def revert_reason(output_hex: str | None) -> str | None:
    """Decodes an Error(string) revert, e.g. 'AprAboveMandate'. None if the output is not one."""
    from eth_abi import decode_abi

    if not output_hex or not output_hex.startswith("0x"):
        return None
    raw = _bytes_of(output_hex)
    if raw[:4].hex() != ERROR_STRING_SELECTOR:
        return None
    (message,) = decode_abi(["string"], raw[4:])
    return message


def open_clients(key_paths: dict[str, str], sdk_dir: str, config_dir: str) -> dict[str, Any]:
    """One SDK client per role, each with its own PEM key. The SDK loads its native library relative to the
    working directory, so the SDK directory is the working directory while the clients are created."""
    for path in (config_dir, sdk_dir):
        if path not in sys.path:
            sys.path.insert(0, path)
    import client_config as sdk_config
    from bcos3sdk.bcos3client import Bcos3Client

    base = sdk_config.client_config
    clients = {}
    previous = os.getcwd()
    os.chdir(sdk_dir)
    try:
        for role, key_path in key_paths.items():
            key = Path(key_path)
            config = type(
                f"Role_{role}",
                (base,),
                {"account_keyfile_path": str(key.parent), "account_keyfile": key.name},
            )
            clients[role] = Bcos3Client(client_config_instance=config)
    finally:
        os.chdir(previous)
    return clients


def address_of(client: Any) -> str:
    """The account address the client signs with."""
    return client.default_from_account_signer.get_keypair().address


def _pending_id(logs: list) -> int | None:
    for log in logs or []:
        topics = log.get("topics", [])
        if topics and topics[0].lower() == APPROVAL_REQUIRED_TOPIC.lower() and len(topics) > 1:
            return _as_int(topics[1])
    return None


class FiscoLedger:
    name = "fisco"

    def __init__(
        self,
        deployment: dict,
        key_paths: dict[str, str],
        payee_addresses: dict[str, str],
        sdk_dir: str,
        config_dir: str,
        receipts_dir: str | None = None,
    ) -> None:
        self.deployment = deployment
        self.contracts = deployment["contracts"]
        self.roles = deployment["roles"]
        self.payee_addresses = payee_addresses
        self.receipts_dir = Path(receipts_dir) if receipts_dir else None
        self.receipts: list[dict] = []
        self.clients = open_clients(key_paths, sdk_dir, config_dir)
        self._abi = {
            name: load_artifact(name)["abi"]
            for name in ("MockStable", "PolicyGuard", "ReceivableRegistry", "FinancingVault", "AgentWallet")
        }

    # ----- low-level send and read -----

    def _send(self, role: str, to: str, abi_name: str, fn: str, args: list) -> ChainResult:
        data = encode_call(self._abi[abi_name], fn, args)
        receipt = self.clients[role].sendRawTransaction(to, None, None, None, function_bin_data=data)
        return self._result(receipt)

    def _result(self, receipt: dict) -> ChainResult:
        status = _as_int(receipt.get("status", 0))
        tx_hash = receipt.get("transactionHash")
        block = _as_int(receipt.get("blockNumber", 0))
        self._record(receipt)
        if status == 0:
            pending = _pending_id(receipt.get("logEntries") or receipt.get("logs"))
            return ChainResult(
                ok=True,
                tx_hash=tx_hash,
                block_number=block,
                pending_id=pending,
                events={"contract_address": receipt.get("contractAddress")},
            )
        reason = revert_reason(receipt.get("output")) or _status_message(status)
        return ChainResult(ok=False, tx_hash=tx_hash, block_number=block, revert_reason=reason)

    def _record(self, receipt: dict) -> None:
        self.receipts.append(receipt)
        if self.receipts_dir:
            self.receipts_dir.mkdir(parents=True, exist_ok=True)
            name = receipt.get("transactionHash", "unknown")
            (self.receipts_dir / f"{name}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    def _read(self, contract: str, fn: str, args: list | None = None) -> str:
        data = encode_call(self._abi[contract], fn, args or [])
        response = self.clients["owner"].call(self.contracts[contract], None, None, None, raw_func_data=data)
        return response.get("output", "0x") if isinstance(response, dict) else str(response)

    def _calldata_for(self, contract: str, fn: str, args: list) -> str:
        return encode_call(self._abi[contract], fn, args)

    def _wallet_execute(
        self,
        role: str,
        target: str,
        inner: str,
        amount: int,
        apr_bps: int,
        fingerprint: str,
        decision_hash: str,
    ) -> ChainResult:
        """AgentWallet.execute: the agent's only call. The guard runs first, then the target."""
        return self._send(
            role,
            self.contracts["AgentWallet"],
            "AgentWallet",
            "execute",
            [target, inner, amount, apr_bps, fingerprint, decision_hash or ZERO32],
        )

    # ----- LedgerAdapter -----

    def register(self, r: RegisterIntent) -> ChainResult:
        doc_hash = r.doc_hash if _is_bytes32(r.doc_hash) else keccak_hex(r.doc_hash)
        due = int(datetime.combine(r.due_date, datetime.min.time()).timestamp())
        inner = self._calldata_for(
            "ReceivableRegistry",
            "register",
            [r.invoice_fingerprint, doc_hash, r.seller_address, to_units(r.face_value, TOKEN_DECIMALS), due],
        )
        return self._wallet_execute(
            "agent", self.contracts["ReceivableRegistry"], inner, 0, 0, r.invoice_fingerprint, ZERO32
        )

    def approve(self, a: ApproveIntent) -> ChainResult:
        return self._send(
            "risk_oracle",
            self.contracts["ReceivableRegistry"],
            "ReceivableRegistry",
            "approve",
            [a.invoice_fingerprint, to_units(a.limit, TOKEN_DECIMALS), a.max_apr_bps, a.decision_hash],
        )

    def execute(self, d: DrawIntent) -> ChainResult:
        lender = self.payee_addresses[f"LENDER:{d.lender_id}"]
        inner = self._calldata_for(
            "FinancingVault",
            "draw",
            [
                d.invoice_fingerprint,
                to_units(d.amount, TOKEN_DECIMALS),
                d.apr_bps,
                lender,
                to_units(d.lender_fee, TOKEN_DECIMALS),
                to_units(d.platform_fee, TOKEN_DECIMALS),
            ],
        )
        return self._wallet_execute(
            "agent",
            self.contracts["FinancingVault"],
            inner,
            to_units(d.amount, TOKEN_DECIMALS),
            d.apr_bps,
            d.invoice_fingerprint,
            d.decision_hash,
        )

    def confirm(self, pending_id: int) -> ChainResult:
        return self._send(
            "approver", self.contracts["AgentWallet"], "AgentWallet", "confirm", [pending_id, True]
        )

    def settle(self, s: SettleIntent) -> ChainResult:
        inner = self._calldata_for(
            "FinancingVault", "repay", [s.invoice_fingerprint, to_units(s.amount_paid, TOKEN_DECIMALS)]
        )
        return self._wallet_execute(
            "agent", self.contracts["FinancingVault"], inner, 0, 0, s.invoice_fingerprint, ZERO32
        )

    def set_mandate(self, mandate: Mandate, payee_addresses: list[str], targets: list[str]) -> ChainResult:
        expires = int(mandate.expires_at.timestamp()) if mandate.expires_at else 0
        result = self._send(
            "owner",
            self.contracts["PolicyGuard"],
            "PolicyGuard",
            "setMandate",
            [
                to_units(mandate.max_amount_per_tx, TOKEN_DECIMALS),
                to_units(mandate.daily_cap, TOKEN_DECIMALS),
                int(mandate.max_ltv * BPS),
                int(mandate.max_apr * BPS),
                to_units(mandate.human_review_above, TOKEN_DECIMALS),
                expires,
                mandate.mandate_hash,
            ],
        )
        for address in payee_addresses:
            result = self._send(
                "owner", self.contracts["PolicyGuard"], "PolicyGuard", "setPayee", [address, True]
            )
        return result

    def deposit(self, lender: str, amount: Decimal) -> ChainResult:
        """Lender liquidity. scripts/deploy_fisco.py funds the vault (TX-3 stand-in) at deploy time."""
        raise NotImplementedError("FISCO liquidity is set by scripts/deploy_fisco.py, not at service start")

    def pause(self, on: bool) -> ChainResult:
        if on:
            return self._send("approver", self.contracts["AgentWallet"], "AgentWallet", "pause", [])
        return self._send("owner", self.contracts["AgentWallet"], "AgentWallet", "unpause", [])

    def anchor_audit(self, root: str, entries: int) -> ChainResult:
        return self._send(
            "agent", self.contracts["AgentWallet"], "AgentWallet", "anchorAudit", [root, entries]
        )

    def health(self) -> bool:
        try:
            return self.clients["owner"].getBlockNumber() >= 0
        except Exception:
            return False

    def mandate_hash_onchain(self) -> str:
        """The mandate hash PolicyGuard holds. Used to check the service's mandate against the chain."""
        return self._read("PolicyGuard", "mandateHash")


def _is_bytes32(value: str) -> bool:
    return isinstance(value, str) and len(value) == 66 and value.startswith("0x")


def _status_message(status: int) -> str:
    return f"TransactionStatus{status}"
