#!/bin/bash

set -e
export ETH_GAS=1000000

# Amount of collateral to join and lock (Wad)
collateral=${1:-1}
# Amount of Dai to draw and exit (Wad)
debt=${2:-75}

mcd -C testnet wrap $collateral > /dev/null
id=$(mcd -C testnet --ilk=ETH-C cdp open | sed -n "s/^Opened: cdp \([0-9]\+\)$/\1/ p") > /dev/null
mcd -C testnet cdp $id lock $ink > /dev/null
mcd -C testnet cdp $id draw $art > /dev/null
echo Created SAFE $id with locked_collateral=$collateral and generated_debt=$debt
