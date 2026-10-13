#!/usr/bin/env bash
# One command for the FISCO demo. Makes sure the chain container, the four nodes and the wallet are running,
# runs scripts/demo.py, then checks every hash the demo wrote against the chain.
#
# Needs the one-time setup in the README (FISCO steps 1 to 6): the chain folder, the node binary, the SDK, the
# keys, the SDK config and the deployment. From the repo root:
#
#   bash services/agent-wallet/scripts/fisco_demo.sh           # the demo, on the deployed contracts
#   bash services/agent-wallet/scripts/fisco_demo.sh --fresh   # redeploy first (a new daily cap)
#
# The daily cap is a rolling 24h total that every run adds to. One full run draws THB 1,504,300 of the demo
# mandate's THB 3,000,000, so a second run within 24 hours fails its large-draw step. Run --fresh before a
# rehearsal or a recording.
#
# The wallet tokens are generated on the first run and kept in fisco-chain/tokens.env (git-ignored).
set -euo pipefail
# Git Bash would rewrite paths such as /repo for docker; keep them as they are.
FRESH=0
if [ "${1:-}" = "--fresh" ]; then FRESH=1; fi
export MSYS_NO_PATHCONV=1

SERVICE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$SERVICE/../.." && pwd)"
CHAIN="$SERVICE/fisco-chain"
CONTAINER=fisco-air
PORT=8003
TOKENS="$CHAIN/tokens.env"
PYTHON="${PYTHON:-python}"

die() { echo "error: $*" >&2; exit 1; }
winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }
healthy() { curl -sf --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; }

command -v docker >/dev/null 2>&1 || die "docker is not installed"
docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop and try again"
[ -d "$CHAIN/accounts" ] || die "no chain folder at $CHAIN. Follow the README's FISCO steps 1 to 6 first"

# Wallet tokens: generated once, then reused.
NEW_TOKENS=0
if [ ! -f "$TOKENS" ]; then
  {
    echo "WALLET_OWNER_TOKEN=$(openssl rand -hex 16)"
    echo "WALLET_APPROVER_TOKEN=$(openssl rand -hex 16)"
    echo "WALLET_RISK_ORACLE_TOKEN=$(openssl rand -hex 16)"
    echo "WALLET_AGENT_TOKEN=$(openssl rand -hex 16)"
  } > "$TOKENS"
  NEW_TOKENS=1
  echo "created $TOKENS"
fi
set -a
# shellcheck disable=SC1090
. "$TOKENS"
set +a

# Container: created once with the chain folder, the repo and the ports mapped to localhost.
if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "creating the container $CONTAINER"
  docker run -d --name "$CONTAINER" \
    -p 127.0.0.1:20200-20203:20200-20203 -p 127.0.0.1:30300-30303:30300-30303 -p "127.0.0.1:$PORT:$PORT" \
    -v "$(winpath "$CHAIN"):/work" -v "$(winpath "$REPO"):/repo" \
    ubuntu:22.04 sleep infinity >/dev/null
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
  docker start "$CONTAINER" >/dev/null
fi

# Nodes: all four must be running.
NODES="$(docker exec "$CONTAINER" bash -c "ps -eo args | grep -c '[f]isco-bcos'" || true)"
if [ "${NODES:-0}" -lt 4 ]; then
  echo "starting the four nodes"
  docker exec "$CONTAINER" bash /work/nodes/127.0.0.1/start_all.sh >/dev/null 2>&1 \
    || die "could not start the nodes (is /work/nodes built? see README step 3)"
  sleep 15
fi

# Contracts: a fresh deployment gives a new guard, with an empty daily-cap ledger.
if [ "$FRESH" = 1 ]; then
  echo "deploying fresh contracts"
  docker exec "$CONTAINER" bash -c "cd /repo/services/agent-wallet && /opt/venv/bin/python scripts/deploy_fisco.py \
    --sdk-dir /opt/python-sdk --config-dir /work/sdk --accounts-dir /work/accounts" >/dev/null \
    || die "the deployment failed; see the output of scripts/deploy_fisco.py"
fi

# Wallet: always restarted, so it runs the current code with the current tokens.
restart_wallet() {
  docker exec "$CONTAINER" bash -c 'ps -eo pid,args | grep "[u]vicorn app.main" | awk "{print \$1}" | xargs -r kill' || true
  sleep 3
  docker exec -d -w /repo \
    -e CHAIN_MODE=fisco -e FISCO_SDK_DIR=/opt/python-sdk -e FISCO_CONFIG_DIR=/work/sdk \
    -e FISCO_RECEIPTS_DIR=/repo/services/agent-wallet/eval/fisco-receipts-demo \
    -e CHAIN_ACCOUNT_KEY_PATH=/work/accounts/agent.pem -e CHAIN_OWNER_KEY_PATH=/work/accounts/deployer.pem \
    -e CHAIN_APPROVER_KEY_PATH=/work/accounts/approver.pem \
    -e CHAIN_RISK_ORACLE_KEY_PATH=/work/accounts/risk_oracle.pem \
    -e CHAIN_DEPLOYMENTS_FILE=/repo/services/agent-wallet/contracts/deployments.json \
    -e WALLET_OWNER_TOKEN="$WALLET_OWNER_TOKEN" -e WALLET_APPROVER_TOKEN="$WALLET_APPROVER_TOKEN" \
    -e WALLET_RISK_ORACLE_TOKEN="$WALLET_RISK_ORACLE_TOKEN" -e WALLET_AGENT_TOKEN="$WALLET_AGENT_TOKEN" \
    -e DEMO_MODE=1 \
    "$CONTAINER" bash -c "/opt/venv/bin/python -m uvicorn app.main:app --app-dir services/agent-wallet \
      --host 0.0.0.0 --port $PORT > /work/wallet.log 2>&1"
  for _ in $(seq 1 60); do
    if healthy; then return 0; fi
    sleep 2
  done
  die "the wallet did not start; see fisco-chain/wallet.log"
}

echo "starting the wallet"
restart_wallet
curl -s "http://127.0.0.1:$PORT/health"
echo

# Demo, then the check of every hash it wrote against the chain.
"$PYTHON" "$(winpath "$SERVICE/scripts/demo.py")" --url "http://127.0.0.1:$PORT" \
  || die "the demo failed. If the host Python has no httpx, install it or set PYTHON"

echo
echo "checking the demo's hashes against the chain"
docker exec "$CONTAINER" bash -c "cd /repo/services/agent-wallet && /opt/venv/bin/python scripts/verify_fisco_hashes.py \
  --sdk-dir /opt/python-sdk --config-dir /work/sdk --accounts-dir /work/accounts \
  --record eval/demo_tx_hashes_fisco.md" 2>&1 | grep -v -E "INFO|WARN" | tee "$SERVICE/eval/fisco-verification-demo.txt"
