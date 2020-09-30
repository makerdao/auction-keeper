#!/bin/bash
dir="$(dirname "$0")"

source testnet.sh
source ../../_virtualenv/bin/activate

# Allows keepers to bid different prices
MODEL=$1
# Outputs keeper logs to separate files
ID=$2
# Chooses collateral type to auction
COLLATERAL_TYPE=${3:-ETH-A}

../../bin/auction-keeper \
    --from-block 1 \
    --rpc-host ${ETH_RPC_URL:?} \
    --rpc-timeout 30 \
    --eth-from ${ACCOUNT_ADDRESS?:} \
    --eth-key ${ACCOUNT_KEY?:} \
    --type collateral \
    --collateral-type ${COLLATERAL_TYPE} \
    --safe-engine-system-coin-target 1000 \
    --keep-system-coin-in-safe-engine-on-exit \
    --model ${dir}/${MODEL} \
    2> >(tee -a ${LOGS_DIR?:}/auction-keeper-${ID}.log >&2)
