#!/bin/bash
set -e
export CURRENT_DIR=$(pwd)

mcd=mcd
#mcd=${CURRENT_DIR}/../../mcd-cli/bin/mcd # (to run mcd-cli from source)

if [ -z $2 ]; then
  echo "Usage: ./create-vault.sh [INK] [ART]"
  exit 1
fi
if [ -z $ETH_FROM ]; then
  echo Please set ETH_FROM to the address to be used for vault creation
  exit 1
fi
if [ -z $ETH_KEYSTORE ]; then
  echo Please set ETH_KEYSTORE to the directory where your private keys reside
  exit 1
fi
if [ -z $ETH_RPC_URL ]; then
  echo Please set ETH_RPC_URL to your node\'s URI
  exit 1
fi

# Amount of collateral to join and lock (Wad)
ink=${1:?}
# Amount of Dai to draw and exit (Wad)
art=${2:?}

#$mcd -C kovan wrap $ink > /dev/null
id=$($mcd -C kovan --ilk=ETH-A cdp open | sed -n "s/^Opened: cdp \([0-9]\+\)$/\1/ p") > /dev/null
$mcd -C kovan cdp $id lock $ink > /dev/null
$mcd -C kovan cdp $id draw $art > /dev/null
echo Created vault $id with ink=$ink and art=$art
