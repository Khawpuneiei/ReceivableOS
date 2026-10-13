#!/usr/bin/env bash
# Write a .env for CI and local QA: .env.example with fake, non-placeholder secrets. Owner: PM.
# The values are test-only and public; never reuse them for a real demo. Usage: scripts/ci_env.sh [out-file]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/.env}"
sed \
  -e 's/^FINGERPRINT_HMAC_KEY=.*/FINGERPRINT_HMAC_KEY=ci-only-fingerprint-key-0123456789abcdef0123456789/' \
  -e 's/^BANK_TOKEN_HMAC_KEY=.*/BANK_TOKEN_HMAC_KEY=ci-only-bank-token-key-0123456789abcdef0123456789/' \
  -e 's/^WALLET_APPROVER_TOKEN=.*/WALLET_APPROVER_TOKEN=ci-only-approver-token/' \
  -e 's/^WALLET_OWNER_TOKEN=.*/WALLET_OWNER_TOKEN=ci-only-owner-token/' \
  -e 's/^WALLET_RISK_ORACLE_TOKEN=.*/WALLET_RISK_ORACLE_TOKEN=ci-only-risk-oracle-token/' \
  -e 's/^WALLET_AGENT_TOKEN=.*/WALLET_AGENT_TOKEN=ci-only-agent-token/' \
  -e 's/^AGENT_CANARY=.*/AGENT_CANARY=ci-only-canary-7f3a/' \
  -e 's/^LLM_API_KEY=.*/LLM_API_KEY=/' \
  -e 's/^CHAIN_MODE=.*/CHAIN_MODE=mock/' \
  "$ROOT/.env.example" >"$OUT"
echo "wrote $OUT (CHAIN_MODE=mock, no LLM key, test-only secrets)"
