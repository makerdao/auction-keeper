#!/bin/bash
dir="$(dirname "$0")"

source testnet.sh
export FLIPPER_ADDRESS=0x226b5c00b65f57f981e5318be22521154c931245

source ../../_virtualenv/bin/activate

# Allows keepers to bid different prices
MODEL=$1
# Outputs keeper logs to separate files
ID=$2

../../bin/auction-keeper \
    --rpc-host ${SERVER_ETH_RPC_HOST:?} \
    --rpc-port ${SERVER_ETH_RPC_PORT?:} \
    --rpc-timeout 30 \
    --eth-from ${ACCOUNT_ADDRESS?:} \
    --eth-key ${ACCOUNT_KEY?:} \
    --cat ${CAT_ADDRESS?:} \
    --vow ${VOW_ADDRESS?:} \
    --flipper ${FLIPPER_ADDRESS} \
    --dai-join ${DAI_JOIN_ADDRESS} \
    --vat-dai-target 300 \
    --keep-dai-in-vat-on-exit \
    --model ${dir}/${MODEL} \
    2> >(tee -a ${LOGS_DIR?:}/auction-keeper-${ID}.log >&2)

