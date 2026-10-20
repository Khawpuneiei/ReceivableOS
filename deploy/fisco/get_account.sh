#!/usr/bin/env bash
# Stand-in for the FISCO console's tools/get_account.sh, which build_chain.sh calls to create the chain's
# governance admin account. deploy/start-fisco.sh builds the chain without auth mode, so that admin account is
# never used: this writes a throwaway key where build_chain.sh expects one and prints an address in the same
# format, instead of downloading the console's script and its keccak tool on every boot.
set -euo pipefail
mkdir -p accounts
openssl ecparam -name secp256k1 -genkey -noout -out accounts/admin.pem
echo "[INFO] Account Address   : 0x$(openssl rand -hex 20)"
