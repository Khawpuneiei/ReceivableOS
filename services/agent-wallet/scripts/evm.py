"""Thin wrappers around forge and cast for the local EVM scripts. Owner: Agent AI engineer.

Only Anvil is supported for now. Transactions use Anvil's unlocked accounts (`--unlocked --from <address>`),
so no private key is read, passed or stored. Every wrapper refuses to run unless the RPC reports Anvil's
chain id (31337), so the unlocked-account path cannot reach a real network.
"""

import json
import subprocess
from pathlib import Path

from Crypto.Hash import keccak

SERVICE = Path(__file__).resolve().parents[1]
CONTRACTS = SERVICE / "contracts"
FOUNDRY_BIN = Path.home() / ".foundry" / "bin"
ANVIL_CHAIN_ID = "31337"


def _bin(name: str) -> str:
    return str(FOUNDRY_BIN / f"{name}.exe")


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def selector(signature: str) -> str:
    """The 4-byte function selector, e.g. 'register(bytes32,...)' -> '0x12ab34cd'."""
    return "0x" + keccak.new(digest_bits=256, data=signature.encode()).digest()[:4].hex()


def calldata(signature: str, args: list) -> str:
    """ABI-encoded calldata for an inner call, via cast (no network)."""
    code, out, err = _run([_bin("cast"), "calldata", signature, *map(str, args)])
    if code != 0:
        raise RuntimeError(f"calldata {signature} failed: {err or out}")
    return out


class Chain:
    def __init__(self, rpc: str) -> None:
        self.rpc = rpc
        code, out, err = _run([_bin("cast"), "chain-id", "--rpc-url", rpc])
        if code != 0 or out != ANVIL_CHAIN_ID:
            raise SystemExit(f"refusing to run: {rpc} is not Anvil (chain id {out or err})")

    def deploy(self, contract: str, sender: str, args: list | None = None) -> str:
        cmd = [
            _bin("forge"),
            "create",
            contract,
            "--rpc-url",
            self.rpc,
            "--unlocked",
            "--from",
            sender,
            "--broadcast",
            "--json",
        ]
        if args:
            cmd += ["--constructor-args", *map(str, args)]
        code, out, err = _run(cmd, cwd=CONTRACTS)
        if code != 0:
            raise RuntimeError(f"deploy {contract} failed: {err or out}")
        return json.loads(out)["deployedTo"]

    def send(self, to: str, signature: str, args: list, sender: str) -> str:
        cmd = [
            _bin("cast"),
            "send",
            to,
            signature,
            *map(str, args),
            "--rpc-url",
            self.rpc,
            "--unlocked",
            "--from",
            sender,
        ]
        code, out, err = _run(cmd)
        if code != 0:
            raise RuntimeError(f"send {signature} failed: {err or out}")
        return out

    def call(self, to: str, signature: str, args: list, sender: str | None = None) -> tuple[int, str]:
        """Returns (exit code, output). A revert shows up in the output with its reason string."""
        cmd = [_bin("cast"), "call", to, signature, *map(str, args), "--rpc-url", self.rpc]
        if sender:
            cmd += ["--from", sender]
        code, out, err = _run(cmd)
        return code, (out or err)

    def read_uint(self, to: str, signature: str, args: list) -> int:
        code, out = self.call(to, signature, args)
        if code != 0:
            raise RuntimeError(f"read {signature} failed: {out}")
        return int(out.split()[0])
