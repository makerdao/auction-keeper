#!/bin/bash
cd "$(dirname "$0")"

export SERVER_ETH_RPC_HOST=http://0.0.0.0
export SERVER_ETH_RPC_PORT=8545

export LOGS_DIR=../logs
mkdir -p ${LOGS_DIR}

export ACCOUNT_ADDRESS=0x57Da1B8F38A5eCF91E9FEe8a047DF0F0A88716A1
export ACCOUNT_KEY="key_file=../../lib/pymaker/tests/config/keys/UnlimitedChain/key4.json,pass_file=/dev/null"

# Multi-collateral DAI, local testnet release of 0.2.10
export CAT_ADDRESS=0x7f8241b7250c5c5368788543e4da2f9a919e9f02
export VOW_ADDRESS=0x8a1567046e610fec30f120bb70df94b50561c1d3
export FLAPPER_ADDRESS=0x0bd7632af5f7020575e59e80abbca739035ac0ec
export FLOPPER_ADDRESS=0x3f2603979a4a185ace9b9c941193704ffbd24f4a
export MKR_ADDRESS=0x1fd8397e8108ada12ec07976d92f773364ba46e7
export DAI_JOIN_ADDRESS=0xd57d9931b305f1bc1622b97c8cc6747e4a9254a0