#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pyflex:$dir/lib/pygasprice-client/


while true
do
    # Just a simple transaction
    python3 tests/testchain/mint_prot.py 0.01 > /dev/null
    # Show change in surplus/debt as auctions run
    python3 tests/testchain/print.py --balances
    sleep 13
done

popd > /dev/null
