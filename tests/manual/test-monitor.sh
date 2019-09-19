#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


while true
do
    # Just a simple transaction
    python3 tests/manual/mint_mkr.py 0.01 > /dev/null
    # Show change in surplus/debt as auctions run
    python3 tests/manual/print.py --balances
    sleep 13
done

popd > /dev/null
