#!/bin/bash
pushd ../.. > /dev/null
dir="$(dirname "$0")"

export PYTHONPATH=$PYTHONPATH:$dir:$dir/lib/pymaker


# To build debt, first run test-flip.sh against keepers which use a model with a low price.

# This loop merely monitors status while the debt is auctioned off.
while true
do
    # Just a simple transaction
    python3 tests/manual/purchase_dai.py 0.01 > /dev/null
    # Shows changes in debt
    python3 tests/manual/print.py
    # Waits for a mainnet-like block interval
    sleep 13
done

popd > /dev/null