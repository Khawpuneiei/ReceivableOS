#!/usr/bin/env bash
# Start the whole stack on a fresh FISCO BCOS chain inside one container (deploy/Dockerfile.fisco). Owner: PM.
# Each boot builds a new FISCO_NODES-node Air chain (default 4), generates the role keys, deploys and wires the five contracts
# (scripts/deploy_fisco.py), then starts the four services and the Streamlit UI on $PORT. Chain state lives on
# the container's disk, so a restart starts from an empty chain, as the mock ledger does.
set -euo pipefail
cd /app

WORK=/work
NODES="$WORK/nodes/127.0.0.1"
log() { echo "[start-fisco] $*"; }

# Secrets shared only by the processes in this container: any left unset gets a fresh random value per boot, so
# none has to be typed into the host's settings. Values set in the environment win.
for name in FINGERPRINT_HMAC_KEY BANK_TOKEN_HMAC_KEY ORCHESTRATOR_TOKEN WALLET_AGENT_TOKEN WALLET_RISK_ORACLE_TOKEN \
    WALLET_OWNER_TOKEN WALLET_APPROVER_TOKEN AGENT_CANARY; do
  if [ -z "${!name:-}" ]; then
    export "$name=$(openssl rand -hex 32)"
  fi
done

# 1. Chain: FISCO_NODES nodes on 127.0.0.1 (default 4, as in services/agent-wallet/README.md; 1 fits a 512 MB
#    host), RPC from 20200 and P2P from 30300. build_chain.sh writes the node keys and the SDK certificates into
#    $WORK/nodes.
COUNT="${FISCO_NODES:-4}"
if [ ! -d "$NODES" ]; then
  log "building the $COUNT-node chain"
  (cd "$WORK" && bash /opt/fisco/build_chain.sh -l "127.0.0.1:$COUNT" -p 30300,20200 -e /opt/fisco/fisco-bcos >/dev/null)
fi
log "starting the nodes"
bash "$NODES/start_all.sh" >/dev/null
for _ in $(seq 1 60); do
  if (exec 3<>/dev/tcp/127.0.0.1/20200) 2>/dev/null; then break; fi
  sleep 1
done

# 2. Role keys (secp256k1 PEM) and the SDK config, as in services/agent-wallet/README.md steps 5 and 6.
mkdir -p "$WORK/accounts" "$WORK/sdk" "$WORK/receipts"
for role in deployer agent approver risk_oracle buyer; do
  [ -f "$WORK/accounts/$role.pem" ] || openssl ecparam -name secp256k1 -genkey -noout -out "$WORK/accounts/$role.pem"
done
for template in services/agent-wallet/fisco/sdk/*.template; do
  cp "$template" "$WORK/sdk/$(basename "$template" .template)"
done
# The template lists four peers; keep only the nodes this chain has.
for i in 0 1 2 3; do
  [ "$i" -lt "$COUNT" ] || sed -i "/^\s*node\.$i=/d" "$WORK/sdk/bcos3_sdk_config.ini"
done

# 3. Contracts: a fresh deployment per boot. It writes the fisco block of contracts/deployments.json.
log "deploying the contracts"
for attempt in 1 2 3; do
  if (cd services/agent-wallet && /opt/venv/bin/python scripts/deploy_fisco.py \
      --sdk-dir /opt/python-sdk --config-dir "$WORK/sdk" --accounts-dir "$WORK/accounts" | grep -vE 'INFO|WARN'); then
    break
  fi
  [ "$attempt" = 3 ] && { log "the contract deployment failed"; exit 1; }
  log "deployment attempt $attempt failed; retrying"
  sleep 5
done

# 4. Services. The agent wallet runs on the SDK's Python 3.10 against the chain; the others as in the mock image.
for s in ocr-ai:8001 policy-ai:8002 orchestrator:8000; do
  python -m uvicorn app.main:app --app-dir "services/${s%%:*}" --host 127.0.0.1 --port "${s##*:}" &
done
CHAIN_MODE=fisco LEDGER_MODE=fisco FISCO_SDK_DIR=/opt/python-sdk FISCO_CONFIG_DIR="$WORK/sdk" \
FISCO_RECEIPTS_DIR="$WORK/receipts" \
CHAIN_ACCOUNT_KEY_PATH="$WORK/accounts/agent.pem" CHAIN_OWNER_KEY_PATH="$WORK/accounts/deployer.pem" \
CHAIN_APPROVER_KEY_PATH="$WORK/accounts/approver.pem" CHAIN_RISK_ORACLE_KEY_PATH="$WORK/accounts/risk_oracle.pem" \
CHAIN_DEPLOYMENTS_FILE=/app/services/agent-wallet/contracts/deployments.json \
  /opt/venv/bin/python -m uvicorn app.main:app --app-dir services/agent-wallet --host 127.0.0.1 --port 8003 &
for _ in $(seq 1 90); do
  up=0
  for port in 8000 8001 8002 8003; do
    curl -sf "http://127.0.0.1:$port/health" >/dev/null && up=$((up + 1))
  done
  [ "$up" = 4 ] && break
  sleep 1
done
log "$up of 4 services up; wallet: $(curl -s http://127.0.0.1:8003/health || true)"

# 5. UI on Render's port.
cd ui
UI_MODE=live exec streamlit run app.py --server.address 0.0.0.0 --server.port "${PORT:-3000}" --server.headless true
